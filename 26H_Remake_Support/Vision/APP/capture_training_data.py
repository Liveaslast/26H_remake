#!/usr/bin/env python3
"""Collect dynamically rectified ROI samples without MSPM0 telemetry."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import math
import os
from pathlib import Path
import re
import sys
import time

# The OpenCV PyPI wheel on Raspberry Pi contains xcb, while WayVNC may make Qt
# choose the unavailable wayland plugin.
if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    if Path("/usr/share/fonts/truetype/dejavu").is_dir():
        os.environ.setdefault(
            "QT_QPA_FONTDIR",
            "/usr/share/fonts/truetype/dejavu",
        )

import cv2
import numpy as np


SUPPORT_ROOT = Path(__file__).resolve().parents[2]
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from Vision.Core.calibration import (  # noqa: E402
    DynamicCalibration,
    DynamicCalibrationError,
    RectificationState,
    SourceRoi,
)
from Vision.Config.config import (  # noqa: E402
    add_config_argument,
    parse_args_with_config,
)
from Vision.Core.dataset import (  # noqa: E402
    LetterboxInfo,
    RoiDatasetWriter,
    SavedSample,
    letterbox_roi,
    yolo_box_from_xywh,
)
from Vision.Core.geometry import (  # noqa: E402
    add_source_roi_arguments,
    require_matching_source_roi,
    source_roi_from_args,
)
from Vision.IO.camera_telemetry import (  # noqa: E402
    CameraMode,
    FixedUSBCamera,
    RuntimeIOError,
    TelemetryAngleSource,
)
from Vision.IO.manual_angle import (  # noqa: E402
    ManualAngleError,
    ManualAngleSource,
)


WINDOW_NAME = "NO-M0 ROI Dataset Capture"
ANNOTATION_WINDOW = "Mark steel ball, 2=accept, C=cancel"
BATCH_WINDOW = "Batch annotation: 1=box N=negative Space=skip X=back Q=return"
LAST_SAVED_WINDOW = "Last saved ROI"


def set_fullscreen(window_name: str) -> None:
    cv2.setWindowProperty(
        window_name,
        cv2.WND_PROP_FULLSCREEN,
        cv2.WINDOW_FULLSCREEN,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "无MSPM0测试版：动态展开白轨道扩展ROI并采集YOLO训练数据。"
        )
    )
    add_config_argument(parser)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--session",
        help="可选会话名；默认使用本地时间，已有非空目录不会被覆盖",
    )
    parser.add_argument("--prefix")
    parser.add_argument("--model-width", type=int)
    parser.add_argument("--model-height", type=int)
    parser.add_argument("--padding-value", type=int)
    parser.add_argument(
        "--angle-deg",
        type=float,
        help="启动时人工输入的摆杆角度",
    )
    parser.add_argument("--angle-step", type=float)
    parser.add_argument(
        "--angle-file",
        type=Path,
        help="可选：持续读取只包含一个角度数字的UTF-8文本文件",
    )
    parser.add_argument(
        "--mcu-telemetry-port",
        help=(
            "可选：读取STM32 0x5A/0x84遥测角度的串口；启用后实际角度"
            "不在容差内时禁止采集"
        ),
    )
    parser.add_argument(
        "--mcu-telemetry-baudrate",
        type=int,
        default=115200,
        help="STM32遥测串口波特率",
    )
    parser.add_argument(
        "--angle-check-tolerance-deg",
        type=float,
        default=0.35,
        help="启用遥测角度核对时允许的角度误差，单位deg",
    )
    parser.add_argument(
        "--angle-check-timeout-ms",
        type=float,
        default=300.0,
        help="启用遥测角度核对时允许的最大遥测年龄，单位ms",
    )
    parser.add_argument("--camera")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--fps", type=float)
    parser.add_argument("--camera-fourcc")
    parser.add_argument("--camera-buffer-size", type=int)
    parser.add_argument("--camera-read-timeout-ms", type=float)
    parser.add_argument("--exposure-time-absolute", type=int)
    parser.add_argument("--allow-dynamic-framerate", action="store_true")
    parser.add_argument(
        "--lock-dynamic-framerate",
        dest="allow_dynamic_framerate",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--warmup-frames", type=int)
    parser.add_argument(
        "--capture-fps",
        type=float,
        help="连续采集模式的保存帧率（默认：5）",
    )
    parser.add_argument(
        "--auto-burst-samples",
        type=int,
        help="每次按C自动采集的数量；0表示按C前一直拍摄",
    )
    parser.add_argument(
        "--capture-rounds",
        type=int,
        default=1,
        help="兼容旧流程的交互式自动采集轮数；手动1/2/C流程下仅用于显示",
    )
    parser.add_argument(
        "--auto-capture",
        action="store_true",
        help="启动后立即连续保存未标注样本",
    )
    parser.add_argument(
        "--manual-capture",
        dest="auto_capture",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--duration",
        type=float,
        help="运行秒数；0表示直到人工退出",
    )
    parser.add_argument(
        "--start-delay",
        type=float,
        default=0.0,
        help="自动采集前倒计时秒数；倒计时发生在相机打开和预热之后",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        help="保存数量上限；0表示不限制",
    )
    parser.add_argument("--source-jpeg-quality", type=int)
    parser.add_argument("--png-compression", type=int)
    parser.add_argument(
        "--no-save-source",
        action="store_true",
        help="不保存1280x720原始帧（不推荐）",
    )
    parser.add_argument(
        "--save-source",
        dest="no_save_source",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--annotation-scale",
        type=float,
        help="人工框选窗口相对640x128训练图的放大倍数",
    )
    parser.add_argument("--no-display", action="store_true")
    parser.add_argument(
        "--display",
        dest="no_display",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    add_source_roi_arguments(parser)
    return parser


def validate_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
    if min(args.model_width, args.model_height) < 32:
        parser.error("模型输入宽高必须至少为32")
    if args.model_width % 32 or args.model_height % 32:
        parser.error("--model-width和--model-height必须是32的倍数")
    if not 0 <= args.padding_value <= 255:
        parser.error("--padding-value必须在[0,255]内")
    if not math.isfinite(args.angle_deg):
        parser.error("--angle-deg必须是有限数值")
    if not math.isfinite(args.angle_step) or args.angle_step <= 0:
        parser.error("--angle-step必须为正数")
    if args.mcu_telemetry_baudrate <= 0:
        parser.error("--mcu-telemetry-baudrate必须为正数")
    if (
        not math.isfinite(args.angle_check_tolerance_deg)
        or args.angle_check_tolerance_deg <= 0
    ):
        parser.error("--angle-check-tolerance-deg必须为正数")
    if (
        not math.isfinite(args.angle_check_timeout_ms)
        or args.angle_check_timeout_ms <= 0
    ):
        parser.error("--angle-check-timeout-ms必须为正数")
    if min(args.width, args.height) < 2 or args.fps <= 0:
        parser.error("相机宽、高、帧率无效")
    if len(args.camera_fourcc) != 4:
        parser.error("--camera-fourcc必须正好包含4个字符")
    if args.camera_buffer_size < 1:
        parser.error("--camera-buffer-size必须至少为1")
    if args.camera_read_timeout_ms <= 0:
        parser.error("--camera-read-timeout-ms必须为正数")
    if args.exposure_time_absolute < 1:
        parser.error("--exposure-time-absolute must be at least 1")
    if args.warmup_frames < 0:
        parser.error("--warmup-frames不能为负数")
    if not math.isfinite(args.capture_fps) or args.capture_fps <= 0:
        parser.error("--capture-fps必须为正数")
    if (
        args.duration < 0
        or args.max_samples < 0
        or args.auto_burst_samples < 0
        or args.capture_rounds < 1
    ):
        parser.error(
            "--duration、--max-samples和--auto-burst-samples不能为负数，"
            "--capture-rounds必须至少为1"
        )
    if not 1 <= args.source_jpeg_quality <= 100:
        parser.error("--source-jpeg-quality必须在[1,100]内")
    if not 0 <= args.png_compression <= 9:
        parser.error("--png-compression必须在[0,9]内")
    if not math.isfinite(args.annotation_scale) or args.annotation_scale < 1:
        parser.error("--annotation-scale必须至少为1")
    if args.no_display and not args.auto_capture:
        parser.error("--no-display必须与--auto-capture一起使用")
    if args.start_delay < 0:
        parser.error("--start-delay不能为负数")
    if (
        args.no_display
        and args.auto_burst_samples
        and args.duration == 0
        and args.max_samples == 0
    ):
        parser.error(
            "--no-display使用自动批次上限时还必须设置"
            "--duration或--max-samples，避免拍完后无限等待"
        )
    if args.session and not re.fullmatch(r"[A-Za-z0-9_-]+", args.session):
        parser.error("--session只能包含字母、数字、下划线和连字符")
    source_roi_from_args(args, parser)


def calibration_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def choose_session_dir(output_root: Path, requested: str | None) -> Path:
    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if requested:
        return root / requested

    base = datetime.now().strftime("session_%Y%m%d_%H%M%S")
    candidate = root / base
    suffix = 2
    while candidate.exists():
        candidate = root / f"{base}_{suffix:02d}"
        suffix += 1
    return candidate


def state_metadata(state: RectificationState) -> dict[str, object]:
    return {
        "requested_angle_deg": state.requested_angle_deg,
        "interpolation_angle_deg": state.interpolation_angle_deg,
        "lower_angle_deg": state.lower_angle_deg,
        "upper_angle_deg": state.upper_angle_deg,
        "interpolation_ratio": state.interpolation_ratio,
        "source_corners_px": state.source_corners_px.tolist(),
        "position_coefficients": state.position_coefficients.tolist(),
        "homography": state.homography.tolist(),
        "source_roi": (
            None if state.source_roi is None else state.source_roi.to_dict()
        ),
    }


def angle_gate_status(
    angle_monitor: TelemetryAngleSource | None,
    *,
    expected_angle_deg: float,
    tolerance_deg: float,
    maximum_age_seconds: float,
    poll: bool = True,
) -> tuple[bool, str]:
    if angle_monitor is None:
        return True, "angle-check=OFF"
    now = time.perf_counter()
    if poll:
        angle_monitor.poll(now)
    reading = angle_monitor.latest(
        maximum_age_seconds=maximum_age_seconds,
        now=now,
    )
    if reading is None:
        return False, "MCU angle: stale/no telemetry"
    error = reading.angle_deg - expected_angle_deg
    ok = abs(error) <= tolerance_deg
    return (
        ok,
        (
            f"MCU={reading.angle_deg:+.2f}deg "
            f"target={expected_angle_deg:+.2f}deg "
            f"err={error:+.2f}deg tol={tolerance_deg:.2f}"
        ),
    )


def print_angle_gate_block(reason: str) -> None:
    print(f"Angle check blocked capture: {reason}", flush=True)


def annotate_ball(
    model_input: np.ndarray,
    letterbox: LetterboxInfo,
    display_scale: float,
) -> tuple[float, float, float, float] | None:
    """Freeze one clean model input and let the operator draw one ball box."""

    enlarged = cv2.resize(
        model_input,
        None,
        fx=display_scale,
        fy=display_scale,
        interpolation=cv2.INTER_CUBIC,
    )
    x1, y1, x2, y2 = letterbox.content_bounds_xyxy
    cv2.rectangle(
        enlarged,
        (
            int(round(x1 * display_scale)),
            int(round(y1 * display_scale)),
        ),
        (
            int(round((x2 - 1) * display_scale)),
            int(round((y2 - 1) * display_scale)),
        ),
        (0, 255, 255),
        1,
    )
    print("拖框只包住钢球，按2确认，按C取消。", flush=True)
    state: dict[str, object] = {
        "dragging": False,
        "start": None,
        "end": None,
    }

    def on_mouse(event: int, x: int, y: int, flags: int, userdata: object) -> None:
        del flags, userdata
        if event == cv2.EVENT_LBUTTONDOWN:
            state["dragging"] = True
            state["start"] = (x, y)
            state["end"] = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and state["dragging"]:
            state["end"] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            state["dragging"] = False
            state["end"] = (x, y)

    cv2.namedWindow(ANNOTATION_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(
        ANNOTATION_WINDOW,
        enlarged.shape[1],
        enlarged.shape[0],
    )
    set_fullscreen(ANNOTATION_WINDOW)
    cv2.setMouseCallback(ANNOTATION_WINDOW, on_mouse)
    selected: tuple[int, int, int, int] | None = None
    while True:
        canvas = enlarged.copy()
        start = state["start"]
        end = state["end"]
        if isinstance(start, tuple) and isinstance(end, tuple):
            cv2.rectangle(canvas, start, end, (0, 0, 255), 2)
        cv2.imshow(ANNOTATION_WINDOW, canvas)
        key = cv2.waitKeyEx(16)
        if key in (ord("c"), ord("C"), 27):
            selected = None
            break
        if key in (ord("2"), 13, 10):
            if not (isinstance(start, tuple) and isinstance(end, tuple)):
                continue
            left = min(start[0], end[0])
            top = min(start[1], end[1])
            right = max(start[0], end[0])
            bottom = max(start[1], end[1])
            selected = (left, top, right - left, bottom - top)
            break
    try:
        cv2.setMouseCallback(ANNOTATION_WINDOW, lambda *args: None)
        cv2.destroyWindow(ANNOTATION_WINDOW)
    except cv2.error:
        pass
    if selected is None or selected[2] <= 0 or selected[3] <= 0:
        return None

    pixel_box = tuple(float(value) / display_scale for value in selected)
    yolo_box = yolo_box_from_xywh(
        pixel_box,
        (model_input.shape[1], model_input.shape[0]),
        minimum_size_px=3.0,
    )
    center_x = yolo_box[0] * model_input.shape[1]
    center_y = yolo_box[1] * model_input.shape[0]
    content_x1, content_y1, content_x2, content_y2 = (
        letterbox.content_bounds_xyxy
    )
    if not (
        content_x1 <= center_x <= content_x2
        and content_y1 <= center_y <= content_y2
    ):
        raise ValueError("钢球框中心落在ROI填充区域，已取消保存")
    return yolo_box


def build_preview(
    model_input: np.ndarray,
    letterbox: LetterboxInfo,
    *,
    angle_deg: float,
    counts: dict[str, int],
    auto_capture: bool,
    capture_fps: float,
    auto_burst_count: int,
    auto_burst_samples: int,
    capture_round_index: int,
    capture_rounds: int,
    angle_gate_ok: bool,
    angle_gate_text: str,
) -> np.ndarray:
    image = model_input.copy()
    x1, y1, x2, y2 = letterbox.content_bounds_xyxy
    cv2.rectangle(
        image,
        (x1, y1),
        (max(x1, x2 - 1), max(y1, y2 - 1)),
        (0, 255, 255),
        1,
    )
    image = cv2.resize(
        image,
        None,
        fx=2.0,
        fy=2.0,
        interpolation=cv2.INTER_NEAREST,
    )
    canvas = cv2.copyMakeBorder(
        image,
        118,
        0,
        0,
        0,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )
    burst_text = (
        "unlimited"
        if auto_burst_samples == 0
        else f"{auto_burst_count}/{auto_burst_samples}"
    )
    auto_text = (
        f"ON {capture_fps:.1f}fps raw={burst_text}"
        if auto_capture
        else f"OFF raw={burst_text}"
    )
    round_text = (
        f"round={capture_round_index}"
        if capture_rounds <= 0
        else f"round={capture_round_index}/{capture_rounds}"
    )
    cv2.putText(
        canvas,
        (
            f"NO-M0 angle={angle_deg:+.3f}deg  "
            f"{round_text}  "
            f"total={counts['total']} pos={counts['positive']} "
            f"neg={counts['negative']} raw={counts['unlabeled']}"
        ),
        (8, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (0, 255, 0),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        f"1: start auto  2: stop round  C: finish angle  auto={auto_text}",
        (8, 52),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "B: box+positive  N: negative  Space/S: one raw  L: label raw  Q/Esc: quit",
        (8, 78),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        angle_gate_text,
        (8, 104),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (0, 255, 0) if angle_gate_ok else (0, 0, 255),
        1,
        cv2.LINE_AA,
    )
    return canvas


def build_batch_preview(
    model_input: np.ndarray,
    *,
    sample_id: str,
    cursor: int,
    total: int,
    counts: dict[str, int],
    display_scale: float,
) -> np.ndarray:
    image = cv2.resize(
        model_input,
        None,
        fx=display_scale,
        fy=display_scale,
        interpolation=cv2.INTER_CUBIC,
    )
    canvas = cv2.copyMakeBorder(
        image,
        76,
        0,
        0,
        0,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )
    cv2.putText(
        canvas,
        (
            f"{sample_id}  {cursor + 1}/{total}  "
            f"pos={counts['positive']} neg={counts['negative']} "
            f"raw={counts['unlabeled']}"
        ),
        (8, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (0, 255, 0),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "1: draw ball  N: no ball  Space/S: skip  X: back  Q/Esc: return",
        (8, 54),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return canvas


def annotate_unlabeled_queue(
    writer: RoiDatasetWriter,
    display_scale: float,
) -> None:
    """Label captured raw frames without leaving the capture program."""

    pending = [
        sample
        for sample in writer.unlabeled_samples
        if (
            writer.session_dir
            / str(sample.record.get("paths", {}).get("model_input", ""))
        ).is_file()
    ]
    if not pending:
        print("当前会话没有待标注图片。", flush=True)
        return

    print(
        f"Batch annotation started: {len(pending)} images. "
        "1=框球，2=确认，N=无球，Space/S=跳过，X=上一步，Q=返回采集。",
        flush=True,
    )
    cv2.namedWindow(BATCH_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(
        BATCH_WINDOW,
        min(1400, int(round(640 * display_scale))),
        int(round(128 * display_scale)) + 100,
    )
    cursor = 0
    actions: list[tuple[int, str, bool]] = []
    try:
        while cursor < len(pending):
            sample = pending[cursor]
            relative = str(sample.record["paths"]["model_input"])
            image_path = writer.session_dir / relative
            model_input = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if model_input is None or model_input.size == 0:
                raise OSError(f"无法读取待标注图片：{image_path}")
            letterbox = LetterboxInfo.from_dict(sample.record["letterbox"])
            preview = build_batch_preview(
                model_input,
                sample_id=sample.sample_id,
                cursor=cursor,
                total=len(pending),
                counts=writer.counts,
                display_scale=display_scale,
            )
            cv2.imshow(BATCH_WINDOW, preview)
            key = cv2.waitKeyEx(0)
            if key in (ord("q"), ord("Q"), 27):
                break

            converted: SavedSample | None = None
            if key in (ord("1"), ord("b"), ord("B")):
                try:
                    yolo_box = annotate_ball(
                        model_input,
                        letterbox,
                        display_scale,
                    )
                    if yolo_box is not None:
                        converted = writer.label_unlabeled(
                            sample.sample_id,
                            label_state="positive",
                            yolo_box=yolo_box,
                        )
                except ValueError as exc:
                    print(f"Positive label cancelled: {exc}", flush=True)
            elif key in (ord("n"), ord("N")):
                converted = writer.label_unlabeled(
                    sample.sample_id,
                    label_state="negative",
                )
            elif key in (ord(" "), ord("s"), ord("S")):
                actions.append((cursor, sample.sample_id, False))
                cursor += 1
                continue
            elif key in (ord("x"), ord("X")):
                if not actions:
                    print("没有可返回的上一步。", flush=True)
                    continue
                previous_cursor, previous_id, was_labelled = actions.pop()
                if was_labelled:
                    writer.reset_to_unlabeled(previous_id)
                    print(f"Returned to raw: {previous_id}", flush=True)
                cursor = previous_cursor
                continue

            if converted is not None:
                describe_saved(converted, writer)
                actions.append((cursor, sample.sample_id, True))
                cursor += 1

        print(
            f"Batch annotation finished: {writer.counts}",
            flush=True,
        )
    finally:
        try:
            cv2.destroyWindow(BATCH_WINDOW)
        except cv2.error:
            pass


def describe_saved(saved: SavedSample, writer: RoiDatasetWriter) -> None:
    counts = writer.counts
    print(
        f"Saved {saved.sample_id}: state={saved.label_state}; "
        f"total={counts['total']} positive={counts['positive']} "
        f"negative={counts['negative']} unlabeled={counts['unlabeled']}",
        flush=True,
    )


def show_last_saved(saved: SavedSample, writer: RoiDatasetWriter) -> None:
    relative_path = saved.record.get("paths", {}).get("model_input")
    if not relative_path:
        return

    image_path = writer.session_dir / relative_path
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        print(f"Preview failed: cannot read {image_path}", flush=True)
        return

    scale = max(1, min(4, 900 // max(1, image.shape[1])))
    preview = cv2.resize(
        image,
        (image.shape[1] * scale, image.shape[0] * scale),
        interpolation=cv2.INTER_NEAREST,
    )
    cv2.imshow(LAST_SAVED_WINDOW, preview)
    cv2.waitKeyEx(1)


def run_buffered_auto_capture(
    *,
    args: argparse.Namespace,
    camera: FixedUSBCamera,
    calibration: DynamicCalibration,
    angle_source: ManualAngleSource,
    angle_monitor: TelemetryAngleSource | None,
    writer: RoiDatasetWriter,
) -> None:
    finish_at = time.perf_counter() + args.duration
    period = 1.0 / args.capture_fps
    next_capture_at = time.perf_counter()
    buffered_frames: list[tuple[np.ndarray, float]] = []
    last_block_print_at = 0.0
    print(
        f"Buffered auto capture: {args.duration:g}s at "
        f"target {args.capture_fps:g}fps...",
        flush=True,
    )

    while time.perf_counter() < finish_at:
        frame, timestamp = camera.read()
        now = time.perf_counter()
        if now < next_capture_at:
            continue
        gate_ok, gate_text = angle_gate_status(
            angle_monitor,
            expected_angle_deg=angle_source.angle_deg,
            tolerance_deg=args.angle_check_tolerance_deg,
            maximum_age_seconds=args.angle_check_timeout_ms / 1000.0,
        )
        if not gate_ok:
            if now - last_block_print_at > 0.5:
                print_angle_gate_block(gate_text)
                last_block_print_at = now
            next_capture_at += period
            while next_capture_at <= now:
                next_capture_at += period
            continue

        buffered_frames.append((frame.copy(), timestamp))
        next_capture_at += period
        while next_capture_at <= now:
            next_capture_at += period
        if args.max_samples and len(buffered_frames) >= args.max_samples:
            break

    print(
        f"Buffered {len(buffered_frames)} frames; saving ROI images...",
        flush=True,
    )
    for index, (frame, timestamp) in enumerate(buffered_frames, start=1):
        if args.angle_file is not None:
            angle_source.refresh_file(args.angle_file)

        source_roi_frame = (
            calibration.crop_source(frame).copy()
            if not args.no_save_source
            else None
        )
        rectified, state = calibration.rectify(
            frame,
            angle_source.angle_deg,
        )
        model_input, letterbox = letterbox_roi(
            rectified,
            (args.model_width, args.model_height),
            padding_value=args.padding_value,
        )
        saved = writer.save_sample(
            source_frame=frame,
            rectified_roi=rectified,
            model_input=model_input,
            source_roi_frame=source_roi_frame,
            captured_monotonic=timestamp,
            angle_deg=angle_source.angle_deg,
            label_state="unlabeled",
            letterbox_info=letterbox,
            extra_metadata=state_metadata(state),
        )
        describe_saved(saved, writer)
        if index % 25 == 0:
            print(
                f"Saved {index}/{len(buffered_frames)} buffered frames...",
                flush=True,
            )


def run(args: argparse.Namespace) -> int:
    calibration_path = args.calibration.expanduser().resolve()
    calibration = DynamicCalibration.load(calibration_path)
    if calibration.source_size is not None and calibration.source_size != (
        args.width,
        args.height,
    ):
        raise RuntimeIOError(
            f"相机尺寸 {args.width}x{args.height} 与标定尺寸 "
            f"{calibration.source_size[0]}x{calibration.source_size[1]} 不一致"
        )
    configured_roi = SourceRoi(
        args.source_roi_x,
        args.source_roi_y,
        args.source_roi_width,
        args.source_roi_height,
    )
    configured_roi.validate_inside((args.width, args.height))
    require_matching_source_roi(calibration.source_roi, configured_roi)

    minimum_angle, maximum_angle = calibration.angle_range_deg
    angle_source = ManualAngleSource(
        angle_deg=args.angle_deg,
        step_deg=args.angle_step,
        minimum_deg=minimum_angle,
        maximum_deg=maximum_angle,
    )
    if args.angle_file is not None:
        angle_source.refresh_file(args.angle_file)

    session_dir = choose_session_dir(args.output_dir, args.session)
    writer = RoiDatasetWriter(
        session_dir,
        prefix=args.prefix,
        save_source=not args.no_save_source,
        source_jpeg_quality=args.source_jpeg_quality,
        png_compression=args.png_compression,
        append_existing=args.session is not None,
    )
    writer.write_session(
        {
            "mode": "manual_angle",
            "warning": (
                "Manual angle is not synchronized with a moving rod and must "
                "not be used for motor control."
            ),
            "calibration_path": str(calibration_path),
            "calibration_sha256": calibration_sha256(calibration_path),
            "geometry_id": calibration.geometry_id,
            "calibration_angle_range_deg": [
                minimum_angle,
                maximum_angle,
            ],
            "rectified_size": {
                "width": calibration.canonical_size[0],
                "height": calibration.canonical_size[1],
            },
            "source_roi": configured_roi.to_dict(),
            "model_input_size": {
                "width": args.model_width,
                "height": args.model_height,
            },
            "letterbox_padding_value": args.padding_value,
            "camera": {
                "device": args.camera,
                "width": args.width,
                "height": args.height,
                "fps": args.fps,
                "fourcc": "MJPG",
                "exposure_time_absolute": args.exposure_time_absolute,
            },
            "ready_for_training": {
                "images": "images/",
                "labels": "labels/",
                "unlabeled_images": "unlabeled/",
                "class_names": {"0": "steel_ball"},
            },
        }
    )

    camera = FixedUSBCamera(
        CameraMode(
            device=args.camera,
            width=args.width,
            height=args.height,
            fps=args.fps,
            fourcc=args.camera_fourcc,
            buffer_size=args.camera_buffer_size,
            disable_dynamic_framerate=not args.allow_dynamic_framerate,
            exposure_time_absolute=args.exposure_time_absolute,
            read_timeout_seconds=args.camera_read_timeout_ms / 1000.0,
        )
    )
    angle_monitor: TelemetryAngleSource | None = None
    if args.mcu_telemetry_port:
        angle_monitor = TelemetryAngleSource(
            args.mcu_telemetry_port,
            args.mcu_telemetry_baudrate,
            request_period_seconds=0.02,
            link_timeout_seconds=args.angle_check_timeout_ms / 1000.0,
            read_timeout_seconds=0.001,
            write_timeout_seconds=0.10,
        )
    print(
        "WARNING: NO-M0 DATA CAPTURE. Change the manual angle only after "
        "the physical rod has been fixed at the same measured angle.",
        flush=True,
    )
    print(
        f"Calibration angle range={minimum_angle:+.3f}.."
        f"{maximum_angle:+.3f}deg; current={angle_source.angle_deg:+.3f}deg",
        flush=True,
    )
    print(f"Dataset session: {session_dir}", flush=True)
    if writer.sample_count:
        print(
            f"Append mode: loaded {writer.sample_count} existing samples; "
            "new images will continue from the next id.",
            flush=True,
        )
    if not args.no_display:
        print(
            "1=开始连续采集未标注样本，2=停止当前轮，C=结束当前角度，"
            "B=有球并框选，N=无球负样本，Space/S=单张未标注，"
            "L=批量标注，X=撤销，Q=退出。",
            flush=True,
        )

    auto_capture = bool(args.auto_capture)
    auto_period = 1.0 / args.capture_fps
    auto_burst_count = 0
    completed_rounds = 0
    capture_round_index = 1
    last_angle_block_print_at = 0.0
    finish_at: float | None = None
    next_auto_at = time.perf_counter()
    try:
        camera.open()
        started = time.perf_counter()
        next_auto_at = started
        if angle_monitor is not None:
            angle_monitor.start()
            first = angle_monitor.wait_for_first_reading(2.0)
            print(
                "MCU angle check enabled: "
                f"actual={first.angle_deg:+.3f}deg, "
                f"expected={angle_source.angle_deg:+.3f}deg, "
                f"tolerance={args.angle_check_tolerance_deg:.3f}deg",
                flush=True,
            )
        finish_at = None if args.duration == 0 else started + args.duration
        camera.warm_up(args.warmup_frames)
        if args.no_display and auto_capture and finish_at is not None:
            if args.start_delay > 0:
                print(
                    "Prepare the ball. Hold it at the release point.",
                    flush=True,
                )
                remaining = int(args.start_delay)
                for second in range(remaining, 0, -1):
                    print(f"Capture starts in {second}...", flush=True)
                    time.sleep(1.0)
                extra = args.start_delay - remaining
                if extra > 0:
                    time.sleep(extra)
                print("GO: release the ball now.", flush=True)
            run_buffered_auto_capture(
                args=args,
                camera=camera,
                calibration=calibration,
                angle_source=angle_source,
                angle_monitor=angle_monitor,
                writer=writer,
            )
            print(
                f"Capture finished: {writer.counts}; session={session_dir}",
                flush=True,
            )
            return 0

        if not args.no_display:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(
                WINDOW_NAME,
                min(1400, args.model_width * 2),
                args.model_height * 2 + 136,
            )

        while finish_at is None or time.perf_counter() < finish_at:
            frame, timestamp = camera.read()
            if args.angle_file is not None:
                angle_source.refresh_file(args.angle_file)

            source_roi_frame = calibration.crop_source(frame).copy()
            rectified, state = calibration.rectify(
                frame,
                angle_source.angle_deg,
            )
            model_input, letterbox = letterbox_roi(
                rectified,
                (args.model_width, args.model_height),
                padding_value=args.padding_value,
            )

            now = time.perf_counter()
            gate_ok, gate_text = angle_gate_status(
                angle_monitor,
                expected_angle_deg=angle_source.angle_deg,
                tolerance_deg=args.angle_check_tolerance_deg,
                maximum_age_seconds=args.angle_check_timeout_ms / 1000.0,
            )
            if auto_capture and now >= next_auto_at:
                if gate_ok:
                    saved = writer.save_sample(
                        source_frame=frame,
                        rectified_roi=rectified,
                        model_input=model_input,
                        source_roi_frame=source_roi_frame,
                        captured_monotonic=timestamp,
                        angle_deg=angle_source.angle_deg,
                        label_state="unlabeled",
                        letterbox_info=letterbox,
                        extra_metadata=state_metadata(state),
                    )
                    describe_saved(saved, writer)
                    auto_burst_count += 1
                else:
                    if now - last_angle_block_print_at > 0.5:
                        print_angle_gate_block(gate_text)
                        last_angle_block_print_at = now
                next_auto_at = now + auto_period
                if (
                    args.auto_burst_samples
                    and auto_burst_count >= args.auto_burst_samples
                ):
                    auto_capture = False
                    completed_rounds += 1
                    capture_round_index = min(
                        completed_rounds + 1,
                        args.capture_rounds,
                    )
                    next_message = (
                        "All capture rounds complete. Press L to annotate them."
                        if completed_rounds >= args.capture_rounds
                        else (
                            f"Prepare round {completed_rounds + 1}/"
                            f"{args.capture_rounds}, then press C."
                        )
                    )
                    print(
                        f"Automatic burst {completed_rounds}/"
                        f"{args.capture_rounds} complete: "
                        f"{auto_burst_count} raw images. {next_message}",
                        flush=True,
                    )

            if args.max_samples and writer.sample_count >= args.max_samples:
                break

            if args.no_display:
                continue

            preview = build_preview(
                model_input,
                letterbox,
                angle_deg=angle_source.angle_deg,
                counts=writer.counts,
                auto_capture=auto_capture,
                capture_fps=args.capture_fps,
                auto_burst_count=auto_burst_count,
                auto_burst_samples=args.auto_burst_samples,
                capture_round_index=capture_round_index,
                capture_rounds=args.capture_rounds,
                angle_gate_ok=gate_ok,
                angle_gate_text=gate_text,
            )
            cv2.imshow(WINDOW_NAME, preview)
            key = cv2.waitKeyEx(1)
            if key in (ord("q"), ord("Q"), 27):
                break

            saved: SavedSample | None = None
            if key == ord("1"):
                if not gate_ok:
                    print_angle_gate_block(gate_text)
                    continue
                if auto_capture:
                    print("Continuous capture is already ON.", flush=True)
                    continue
                auto_capture = True
                auto_burst_count = 0
                capture_round_index = completed_rounds + 1
                next_auto_at = time.perf_counter()
                print(
                    f"Round {capture_round_index} capture started: "
                    f"{args.capture_fps:g}fps. Press 2 to stop this round; "
                    "press C to finish this angle.",
                    flush=True,
                )
            elif key == ord("2"):
                if not auto_capture:
                    print("Continuous capture is already OFF.", flush=True)
                    continue
                auto_capture = False
                if auto_burst_count > 0:
                    completed_rounds += 1
                    capture_round_index = completed_rounds + 1
                print(
                    f"Round {completed_rounds} stopped: "
                    f"{auto_burst_count} raw images. Press 1 for another "
                    "round, L to annotate, or C to finish this angle.",
                    flush=True,
                )
            elif key in (ord("b"), ord("B")):
                if not gate_ok:
                    print_angle_gate_block(gate_text)
                    continue
                try:
                    yolo_box = annotate_ball(
                        model_input,
                        letterbox,
                        args.annotation_scale,
                    )
                except ValueError as exc:
                    print(f"Positive sample cancelled: {exc}", flush=True)
                    yolo_box = None
                if yolo_box is not None:
                    saved = writer.save_sample(
                        source_frame=frame,
                        rectified_roi=rectified,
                        model_input=model_input,
                        source_roi_frame=source_roi_frame,
                        captured_monotonic=timestamp,
                        angle_deg=angle_source.angle_deg,
                        label_state="positive",
                        yolo_box=yolo_box,
                        letterbox_info=letterbox,
                        extra_metadata=state_metadata(state),
                    )
            elif key in (ord("n"), ord("N")):
                if not gate_ok:
                    print_angle_gate_block(gate_text)
                    continue
                saved = writer.save_sample(
                    source_frame=frame,
                    rectified_roi=rectified,
                    model_input=model_input,
                    source_roi_frame=source_roi_frame,
                    captured_monotonic=timestamp,
                    angle_deg=angle_source.angle_deg,
                    label_state="negative",
                    letterbox_info=letterbox,
                    extra_metadata=state_metadata(state),
                )
            elif key in (ord(" "), ord("s"), ord("S")):
                if not gate_ok:
                    print_angle_gate_block(gate_text)
                    continue
                saved = writer.save_sample(
                    source_frame=frame,
                    rectified_roi=rectified,
                    model_input=model_input,
                    source_roi_frame=source_roi_frame,
                    captured_monotonic=timestamp,
                    angle_deg=angle_source.angle_deg,
                    label_state="unlabeled",
                    letterbox_info=letterbox,
                    extra_metadata=state_metadata(state),
                )
            elif key in (ord("c"), ord("C")):
                if auto_capture:
                    auto_capture = False
                    if auto_burst_count > 0:
                        completed_rounds += 1
                print(
                    f"Angle {angle_source.angle_deg:+.3f}deg capture "
                    f"finished: rounds={completed_rounds}, counts="
                    f"{writer.counts}. Starting batch annotation...",
                    flush=True,
                )
                annotate_unlabeled_queue(writer, args.annotation_scale)
                break
            elif key in (ord("l"), ord("L")):
                if auto_capture:
                    auto_capture = False
                    print(
                        "Continuous capture stopped before batch annotation.",
                        flush=True,
                    )
                annotate_unlabeled_queue(writer, args.annotation_scale)
                next_auto_at = time.perf_counter()
            elif key in (ord("x"), ord("X")):
                removed = writer.undo_last()
                if removed is None:
                    print("本次会话还没有可撤销样本。", flush=True)
                else:
                    print(f"Undone: {removed.sample_id}", flush=True)
            elif angle_source.handle_key(key):
                print(
                    f"Manual angle: {angle_source.angle_deg:+.3f}deg",
                    flush=True,
                )

            if saved is not None:
                describe_saved(saved, writer)
                if saved.label_state == "unlabeled":
                    show_last_saved(saved, writer)
                if args.max_samples and writer.sample_count >= args.max_samples:
                    break

        print(
            f"Capture finished: {writer.counts}; session={session_dir}",
            flush=True,
        )
        return 0
    finally:
        if angle_monitor is not None:
            angle_monitor.stop()
        camera.close()
        cv2.destroyAllWindows()


def main() -> int:
    parser = build_parser()
    args = parse_args_with_config(
        parser,
        sections=("vision_geometry", "roi_capture"),
    )
    validate_args(args, parser)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("ROI data capture stopped.", flush=True)
        return 130
    except (
        DynamicCalibrationError,
        ManualAngleError,
        RuntimeIOError,
        FileExistsError,
        OSError,
        ValueError,
        cv2.error,
    ) as exc:
        print(f"ROI data capture failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
