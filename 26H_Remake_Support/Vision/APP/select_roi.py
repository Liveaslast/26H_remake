#!/usr/bin/env python3
"""Interactively select the fixed source ROI from the live camera frame."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import numpy as np

if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    if Path("/usr/share/fonts/truetype/dejavu").is_dir():
        os.environ.setdefault(
            "QT_QPA_FONTDIR",
            "/usr/share/fonts/truetype/dejavu",
        )

import cv2


SUPPORT_ROOT = Path(__file__).resolve().parents[2]
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from Vision.IO.camera_telemetry import CameraMode, FixedUSBCamera, RuntimeIOError  # noqa: E402
from Vision.Config.config import add_config_argument, parse_args_with_config  # noqa: E402
from Vision.Core.calibration import DynamicCalibration, DynamicCalibrationError  # noqa: E402
from Vision.Core.geometry import (  # noqa: E402
    add_source_roi_arguments,
    draw_source_roi_overlay,
    source_roi_from_args,
)


LIVE_WINDOW = "Select source ROI - live"
SELECT_WINDOW = "Drag source ROI, ENTER=accept, C=cancel"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open the camera and print source_roi pixel coordinates."
    )
    add_config_argument(parser)
    add_source_roi_arguments(parser)
    parser.add_argument("--camera", default="/dev/video0")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--camera-fourcc", default="MJPG")
    parser.add_argument("--camera-buffer-size", type=int, default=2)
    parser.add_argument("--camera-read-timeout-ms", type=float, default=500.0)
    parser.add_argument("--exposure-time-absolute", type=int, default=20)
    parser.add_argument(
        "--allow-dynamic-framerate",
        action="store_true",
        help="Do not force exposure_dynamic_framerate=0.",
    )
    parser.add_argument("--warmup-frames", type=int, default=20)
    parser.add_argument(
        "--preview",
        type=Path,
        default=Path("source_roi_preview.png"),
        help="Path for the annotated preview image.",
    )
    parser.add_argument("--reference-image", type=Path)
    parser.add_argument("--reference-calibration", type=Path)
    parser.add_argument("--reference-angle", type=float)
    parser.add_argument("--alignment-tolerance-px", type=float, default=4.0)
    parser.add_argument("--stable-frames", type=int, default=10)
    return parser


def draw_overlay(frame, text: str):
    canvas = frame.copy()
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1] - 1, 64), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        text,
        (12, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.78,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    return canvas


def clean_reference_markup(image):
    blue, green, red = cv2.split(image)
    mask = np.uint8((green > red * 1.45) & (green > blue * 1.45) & (green > 70)) * 255
    return cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)


def measure_pipe_edges(crop, anchors, expected, radius=24):
    gray = cv2.GaussianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    measurements = []
    for x, (top_hint, bottom_hint) in zip(anchors, expected):
        profile = np.median(gray[:, max(0, x - 10):x + 11], axis=1)
        gradient = np.gradient(profile)
        edges = []
        for hint, direction in ((top_hint, 1), (bottom_hint, -1)):
            start = max(3, int(round(hint)) - radius)
            stop = min(crop.shape[0] - 3, int(round(hint)) + radius + 1)
            if stop <= start:
                edges = []
                break
            region = direction * gradient[start:stop]
            index = int(np.argmax(region))
            if region[index] < 6.0:
                edges = []
                break
            edges.append(start + index)
        measurements.append(tuple(edges) if len(edges) == 2 and edges[1] - edges[0] > 35 else None)
    return measurements


def measure_pipe_corners(crop, hints, radius=24):
    left_hint = (hints[0, 0] + hints[3, 0]) / 2
    right_hint = (hints[1, 0] + hints[2, 0]) / 2
    anchors = np.rint(np.linspace(left_hint, right_hint, 5)[1:-1]).astype(int)
    expected = [
        (np.interp(x, hints[:2, 0], hints[:2, 1]),
         np.interp(x, hints[[3, 2], 0], hints[[3, 2], 1]))
        for x in anchors
    ]
    edges = measure_pipe_edges(crop, anchors, expected, radius=radius)
    if any(pair is None for pair in edges):
        return None

    gray = cv2.GaussianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    mid_y = int(round(np.mean(hints[:, 1])))
    profile = np.median(gray[max(0, mid_y - 12):mid_y + 13, :], axis=0)
    gradient = np.gradient(profile)
    ends = []
    for hint, direction in ((left_hint, 1), (right_hint, -1)):
        start = max(3, int(round(hint)) - radius)
        stop = min(crop.shape[1] - 3, int(round(hint)) + radius + 1)
        if stop <= start:
            return None
        region = direction * gradient[start:stop]
        index = int(np.argmax(region))
        if region[index] < 6.0:
            return None
        ends.append(start + index)
    if ends[1] - ends[0] < crop.shape[1] * 0.6:
        return None

    top = np.polyfit(anchors, [pair[0] for pair in edges], 1)
    bottom = np.polyfit(anchors, [pair[1] for pair in edges], 1)
    corners = np.array([
        (ends[0], np.polyval(top, ends[0])),
        (ends[1], np.polyval(top, ends[1])),
        (ends[1], np.polyval(bottom, ends[1])),
        (ends[0], np.polyval(bottom, ends[0])),
    ])
    if np.any(corners[:, 1] < 0) or np.any(corners[:, 1] >= crop.shape[0]):
        return None
    return corners


def load_alignment_reference(args, roi, parser):
    requested = (args.reference_image, args.reference_calibration, args.reference_angle)
    if not any(value is not None for value in requested):
        return None
    if any(value is None for value in requested):
        parser.error("参考图模式必须同时提供 --reference-image、--reference-calibration 和 --reference-angle")
    try:
        calibration = DynamicCalibration.load(args.reference_calibration)
        if calibration.source_roi != roi:
            parser.error("参考标定的 source_roi 与当前配置不一致")
        if not any(abs(sample.angle_deg - args.reference_angle) < 1e-3 for sample in calibration.samples):
            parser.error("参考角度必须是标定 JSON 中实际采集的角度，不能使用插值角度")
        state = calibration.state_for_angle(args.reference_angle)
    except DynamicCalibrationError as exc:
        parser.error(str(exc))
    image = cv2.imread(str(args.reference_image))
    if image is None or image.shape[:2] != (roi.height, roi.width):
        parser.error(f"参考图必须是原始粗 ROI 图，尺寸为 {roi.width}x{roi.height}；不能使用 YOLO 展开图")
    measured = measure_pipe_corners(clean_reference_markup(image), state.source_corners_px, radius=18)
    if measured is None:
        parser.error("参考图未能可靠定位水管四角；请换一张清晰的原始 ROI 图")
    return image, measured


def draw_alignment(frame, roi, reference_corners, live_corners, stable, required):
    panel_top = max(66, frame.shape[0] - 150)
    cv2.rectangle(frame, (0, panel_top), (min(920, frame.shape[1] - 1), frame.shape[0] - 1), (0, 0, 0), -1)
    if live_corners is None:
        status = "EDGE NOT FOUND - adjust camera / lighting"
        errors = [float("nan")] * 4
        color = (0, 100, 255)
    else:
        errors = np.linalg.norm(live_corners - reference_corners, axis=1)
        status = f"FOUR CORNERS CLOSE {stable}/{required}" if stable else "FOUR CORNERS DIFFER"
        color = (0, 220, 0) if stable >= required else (0, 180, 255)
        for point in live_corners:
            cv2.circle(frame, (int(round(roi.x + point[0])), int(round(roi.y + point[1]))), 4, color, -1)
    cv2.putText(frame, status, (12, panel_top + 27), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
    for index, (label, error) in enumerate(zip(("TL", "TR", "BR", "BL"), errors)):
        row = index // 2
        column = index % 2
        message = f"{label}: {error:.1f} px" if np.isfinite(error) else f"{label}: --"
        cv2.putText(frame, message, (12 + column * 330, panel_top + 64 + row * 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
    cv2.putText(frame, "Reference corners: red  |  detected corners: colored",
                (12, panel_top + 131), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    for point in reference_corners:
        cv2.drawMarker(frame, (int(round(roi.x + point[0])), int(round(roi.y + point[1]))),
                       (0, 0, 255), cv2.MARKER_CROSS, 12, 2)


def main() -> int:
    parser = build_parser()
    args = parse_args_with_config(parser, sections=("vision_geometry",))
    current_roi = source_roi_from_args(args, parser)
    reference = load_alignment_reference(args, current_roi, parser)
    if args.alignment_tolerance_px <= 0 or args.stable_frames < 1:
        parser.error("对齐容差和稳定帧数必须为正数")
    mode = CameraMode(
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
    camera = FixedUSBCamera(mode)
    frozen = None
    stable = 0
    try:
        camera.open()
        camera.warm_up(args.warmup_frames)
        cv2.namedWindow(LIVE_WINDOW, cv2.WINDOW_NORMAL)
        print(
            f"Current source ROI: {current_roi.xywh}; "
            "SPACE: freeze/select another ROI; Q/Esc: quit",
            flush=True,
        )
        while True:
            frame, _ = camera.read()
            canvas = draw_source_roi_overlay(frame, current_roi)
            canvas = draw_overlay(
                canvas,
                "Current ROI: green; guard: yellow; SPACE select; Q/Esc quit",
            )
            if reference is not None:
                crop = current_roi.crop(frame)
                live_corners = measure_pipe_corners(crop, reference[1])
                if live_corners is not None and np.max(np.linalg.norm(live_corners - reference[1], axis=1)) <= args.alignment_tolerance_px:
                    stable = min(stable + 1, args.stable_frames)
                else:
                    stable = 0
                draw_alignment(canvas, current_roi, reference[1], live_corners, stable, args.stable_frames)
                cv2.imshow("Reference (top) / live ROI (bottom)", np.vstack((reference[0], crop)))
            cv2.imshow(LIVE_WINDOW, canvas)
            key = cv2.waitKeyEx(1)
            if key in (ord("q"), ord("Q"), 27):
                return 130
            if key == ord(" "):
                frozen = frame.copy()
                break
        cv2.destroyWindow(LIVE_WINDOW)

        roi = cv2.selectROI(
            SELECT_WINDOW,
            frozen,
            fromCenter=False,
            showCrosshair=True,
        )
        cv2.destroyWindow(SELECT_WINDOW)
        x, y, width, height = (int(round(value)) for value in roi)
        if width < 2 or height < 2:
            print("ROI cancelled or too small.", flush=True)
            return 1

        preview = frozen.copy()
        cv2.rectangle(
            preview,
            (x, y),
            (x + width - 1, y + height - 1),
            (0, 255, 255),
            2,
        )
        cv2.putText(
            preview,
            f"source_roi=({x}, {y}, {width}, {height})",
            (12, max(32, y - 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.78,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
        preview_path = args.preview.expanduser().resolve()
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(preview_path), preview)

        print("", flush=True)
        print("Selected source ROI:", flush=True)
        print(f"source_roi_x = {x}", flush=True)
        print(f"source_roi_y = {y}", flush=True)
        print(f"source_roi_width = {width}", flush=True)
        print(f"source_roi_height = {height}", flush=True)
        print("", flush=True)
        print("Command arguments:", flush=True)
        print(
            f"--source-roi-x {x} --source-roi-y {y} "
            f"--source-roi-width {width} --source-roi-height {height}",
            flush=True,
        )
        print(f"Preview saved: {preview_path}", flush=True)
        return 0
    except RuntimeIOError as exc:
        print(f"ROI selection failed: {exc}", flush=True)
        return 1
    finally:
        camera.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
