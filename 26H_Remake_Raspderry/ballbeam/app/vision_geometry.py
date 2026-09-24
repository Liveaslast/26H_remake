"""Shared fixed-source-ROI CLI and validation helpers."""

from __future__ import annotations

import argparse

import cv2
import numpy as np

from ..vision.calibration import DynamicCalibrationError, SourceRoi


def add_source_roi_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare the full-frame crop shared by calibration and runtime."""

    parser.add_argument("--source-roi-x", type=int)
    parser.add_argument("--source-roi-y", type=int)
    parser.add_argument("--source-roi-width", type=int)
    parser.add_argument("--source-roi-height", type=int)


def source_roi_from_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> SourceRoi:
    """Validate the configured crop against the requested camera mode."""

    try:
        roi = SourceRoi(
            x=args.source_roi_x,
            y=args.source_roi_y,
            width=args.source_roi_width,
            height=args.source_roi_height,
        )
        roi.validate_inside((args.width, args.height))
    except (AttributeError, DynamicCalibrationError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    return roi


def require_matching_source_roi(
    calibration_roi: SourceRoi | None,
    configured_roi: SourceRoi,
) -> None:
    """Reject legacy or mismatched geometry before any frame is processed."""

    if calibration_roi is None:
        raise DynamicCalibrationError(
            "标定文件没有固定粗ROI；请使用当前1280x256方案重新标定"
        )
    if calibration_roi != configured_roi:
        raise DynamicCalibrationError(
            f"配置粗ROI={configured_roi.xywh} 与标定粗ROI="
            f"{calibration_roi.xywh} 不一致"
        )


def draw_source_roi_overlay(
    frame: np.ndarray,
    roi: SourceRoi,
    *,
    guard_px: int = 32,
) -> np.ndarray:
    """Show the fixed crop and the desired hardware framing guard."""

    canvas = frame.copy()
    x1, y1, x2, y2 = roi.bounds_xyxy
    cv2.rectangle(canvas, (x1, y1), (x2 - 1, y2 - 1), (0, 255, 0), 2)
    guard = max(0, min(int(guard_px), (roi.height - 2) // 2))
    if guard:
        cv2.rectangle(
            canvas,
            (x1 + guard, y1 + guard),
            (x2 - 1 - guard, y2 - 1 - guard),
            (0, 255, 255),
            1,
        )
    cv2.putText(
        canvas,
        f"source ROI={roi.width}x{roi.height} at ({roi.x},{roi.y}); guard={guard}px",
        (12, min(frame.shape[0] - 12, y1 + 28)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    return canvas


__all__ = [
    "add_source_roi_arguments",
    "draw_source_roi_overlay",
    "require_matching_source_roi",
    "source_roi_from_args",
]
