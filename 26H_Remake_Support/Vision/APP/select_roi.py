#!/usr/bin/env python3
"""Interactively select the fixed source ROI from the live camera frame."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

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


LIVE_WINDOW = "Select source ROI - live"
SELECT_WINDOW = "Drag source ROI, ENTER=accept, C=cancel"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open the camera and print source_roi pixel coordinates."
    )
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


def main() -> int:
    args = build_parser().parse_args()
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
    try:
        camera.open()
        camera.warm_up(args.warmup_frames)
        cv2.namedWindow(LIVE_WINDOW, cv2.WINDOW_NORMAL)
        print("SPACE: freeze current frame; Q/Esc: quit", flush=True)
        while True:
            frame, _ = camera.read()
            canvas = draw_overlay(
                frame,
                "SPACE freeze/select source ROI; Q/Esc quit",
            )
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
