#!/usr/bin/env python3
"""不读取MSPM0，由操作者人工设定摆杆角度的测试标定程序。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

# OpenCV PyPI轮子只带xcb插件；树莓派WayVNC会让Qt误选wayland。
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
    AngleCalibrationSample,
    DynamicCalibration,
    DynamicCalibrationError,
    SourceRoi,
)
from Vision.Core.geometry import draw_source_roi_overlay  # noqa: E402
from Vision.Config.config import (  # noqa: E402
    add_config_argument,
    parse_args_with_config,
)
from Vision.Core.calibration_workflow import (  # noqa: E402
    add_common_calibration_arguments,
    build_calibration_geometry,
    prepare_calibration_sample,
    save_calibration_previews,
    validate_common_calibration_args,
)
from Vision.IO.camera_telemetry import (  # noqa: E402
    CameraMode,
    FixedUSBCamera,
    RuntimeIOError,
)
def capture_manual_frame(
    camera: FixedUSBCamera,
    *,
    assumed_angle_deg: float,
    minimum_settle_seconds: float,
    source_roi: SourceRoi,
) -> np.ndarray:
    """等待操作者按空格，角度值完全来自命令行列表。"""

    window = "NO-M0 calibration - live"
    entered_at = time.monotonic()
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    print(
        f"[TEST ONLY] 请用量角器把摆杆调到 {assumed_angle_deg:+.2f}deg。"
        "稳定后按空格；程序会直接相信这个人工角度。",
        flush=True,
    )
    while True:
        frame, _ = camera.read()
        elapsed = time.monotonic() - entered_at
        ready = elapsed >= minimum_settle_seconds
        canvas = draw_source_roi_overlay(frame, source_roi)
        cv2.rectangle(canvas, (0, 0), (920, 86), (0, 0, 0), -1)
        cv2.putText(
            canvas,
            (
                f"TEST ONLY / NO M0 / assumed angle="
                f"{assumed_angle_deg:+.3f}deg"
            ),
            (12, 29),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            (
                "Measure the physical angle, then press SPACE"
                if ready
                else f"Wait for settling: {minimum_settle_seconds-elapsed:.1f}s"
            ),
            (12, 63),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (0, 220, 0) if ready else (0, 200, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            "Q/Esc: quit",
            (12, 82),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.imshow(window, canvas)
        key = cv2.waitKeyEx(1)
        if key in (ord("q"), ord("Q"), 27):
            cv2.destroyWindow(window)
            raise KeyboardInterrupt
        if key == ord(" ") and ready:
            cv2.destroyWindow(window)
            return frame.copy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="测试版：不连接MSPM0，人工设定每个摆杆标定角度。"
    )
    add_config_argument(parser)
    add_common_calibration_arguments(parser)
    parser.add_argument("--minimum-settle-seconds", type=float)
    return parser


def validate_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> tuple[list[float], list[float]]:
    geometry = validate_common_calibration_args(args, parser)
    if args.minimum_settle_seconds < 0:
        parser.error("--minimum-settle-seconds 不能为负数")
    return list(geometry.angles), list(geometry.positions)


def run(
    args: argparse.Namespace,
    angles: list[float],
    positions: list[float],
) -> int:
    geometry = build_calibration_geometry(args, angles, positions)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_size = geometry.canonical_size
    mode = geometry.camera_mode
    camera = FixedUSBCamera(mode)
    samples: list[AngleCalibrationSample] = []

    print(
        "WARNING: test-only calibration; angle values are manually assumed. "
        f"Rectified={canonical_size[0]}x{canonical_size[1]}",
        flush=True,
    )
    try:
        camera.open()
        camera.warm_up(args.warmup_frames)
        for index, assumed_angle in enumerate(angles):
            frame = capture_manual_frame(
                camera,
                assumed_angle_deg=assumed_angle,
                minimum_settle_seconds=args.minimum_settle_seconds,
                source_roi=geometry.source_roi,
            )
            prepared = prepare_calibration_sample(
                frame,
                angle_deg=assumed_angle,
                positions=geometry.positions,
                canonical_size=canonical_size,
                source_roi=geometry.source_roi,
                corner_window=(
                    f"NO-M0 {assumed_angle:+g}: expanded track ROI corners"
                ),
                position_window=f"NO-M0 {assumed_angle:+g}: position marks",
                maximum_width=args.max_display_width,
                maximum_height=args.max_display_height,
            )
            samples.append(prepared.sample)
            stem = f"manual_{index:02d}_{assumed_angle:+07.3f}".replace(
                "+",
                "p",
            )
            save_calibration_previews(output_dir, stem, prepared)

        calibration = DynamicCalibration(
            canonical_size=canonical_size,
            source_size=(mode.width, mode.height),
            source_roi=geometry.source_roi,
            samples=tuple(samples),
            maximum_angle_margin_deg=args.maximum_angle_margin,
            metadata={
                "test_only": True,
                "angle_source": "manual_assumed",
                "created_local_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "requested_angles_deg": angles,
                "positions_cm": positions,
                "rod_length_cm": args.rod_length_cm,
                "groove_width_cm": args.groove_width_cm,
            },
        )
        output_path = output_dir / "dynamic_calibration_manual.json"
        calibration.save(output_path)
        print(f"Test calibration saved: {output_path}", flush=True)
        return 0
    finally:
        camera.close()
        cv2.destroyAllWindows()


def main() -> int:
    parser = build_parser()
    args = parse_args_with_config(
        parser,
        sections=(
            "vision_geometry",
            "calibration",
            "manual_calibration",
        ),
    )
    angles, positions = validate_args(args, parser)
    try:
        return run(args, angles, positions)
    except KeyboardInterrupt:
        print("Test calibration cancelled.", flush=True)
        return 130
    except (DynamicCalibrationError, RuntimeIOError, cv2.error) as exc:
        print(f"Test calibration failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
