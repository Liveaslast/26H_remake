"""Shared geometry, validation, and sample preparation for calibration apps."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .calibration import (
    AngleCalibrationSample,
    SourceRoi,
    compute_homography,
    fit_position_polynomial,
    order_quad_points,
)
from .geometry import (
    add_source_roi_arguments,
    source_roi_from_args,
)
from ..IO.camera_telemetry import CameraMode, RuntimeIOError
from .calibration_ui import (
    draw_rectified_preview,
    draw_source_preview,
    parse_number_list,
    select_points,
)


@dataclass(frozen=True, slots=True)
class CalibrationGeometry:
    angles: tuple[float, ...]
    positions: tuple[float, ...]
    canonical_size: tuple[int, int]
    source_roi: SourceRoi
    camera_mode: CameraMode


@dataclass(frozen=True, slots=True)
class PreparedCalibrationSample:
    sample: AngleCalibrationSample
    source_preview: np.ndarray
    rectified_preview: np.ndarray


def add_common_calibration_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Declare calibration parameters; TOML supplies their defaults."""

    parser.add_argument("--angles")
    parser.add_argument("--positions")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--rectified-width", type=int)
    parser.add_argument("--rectified-height", type=int)
    parser.add_argument("--rod-length-cm", type=float)
    parser.add_argument("--groove-width-cm", type=float)
    parser.add_argument("--maximum-angle-margin", type=float)
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
    parser.add_argument("--max-display-width", type=int)
    parser.add_argument("--max-display-height", type=int)
    add_source_roi_arguments(parser)


def validate_common_calibration_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> CalibrationGeometry:
    try:
        angles = parse_number_list(args.angles, "--angles")
        positions = parse_number_list(args.positions, "--positions")
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if len(angles) < 2 or np.any(np.diff(angles) <= 0):
        parser.error("--angles 至少包含两个严格递增的角度")
    if len(positions) < 3 or np.any(np.diff(positions) <= 0):
        parser.error("--positions 至少包含三个严格递增的位置")
    if args.rectified_width < 2 or args.rectified_height < 0:
        parser.error("展开宽度必须至少为2，高度不能为负数")
    if args.rectified_height == 1:
        parser.error("--rectified-height 只能为0或至少为2")
    if args.rod_length_cm <= 0 or args.groove_width_cm <= 0:
        parser.error("摆杆长度和凹槽宽度必须为正数")
    if args.maximum_angle_margin < 0:
        parser.error("--maximum-angle-margin 不能为负数")
    if args.exposure_time_absolute < 1:
        parser.error("--exposure-time-absolute must be at least 1")
    if args.warmup_frames < 0:
        parser.error("--warmup-frames 不能为负数")
    if min(args.width, args.height) < 2 or args.fps <= 0:
        parser.error("相机宽、高、帧率无效")
    if len(args.camera_fourcc) != 4:
        parser.error("--camera-fourcc必须正好包含4个字符")
    if args.camera_buffer_size < 1:
        parser.error("--camera-buffer-size必须至少为1")
    if args.camera_read_timeout_ms <= 0:
        parser.error("--camera-read-timeout-ms必须为正数")
    if min(args.max_display_width, args.max_display_height) < 100:
        parser.error("标定窗口最大尺寸过小")
    source_roi_from_args(args, parser)

    return build_calibration_geometry(args, angles, positions)


def build_calibration_geometry(
    args: argparse.Namespace,
    angles: list[float] | tuple[float, ...],
    positions: list[float] | tuple[float, ...],
) -> CalibrationGeometry:
    """Build immutable geometry after CLI validation."""

    rectified_height = args.rectified_height
    if rectified_height == 0:
        rectified_height = max(
            2,
            int(
                round(
                    args.rectified_width
                    * args.groove_width_cm
                    / args.rod_length_cm
                )
            ),
        )
    return CalibrationGeometry(
        angles=tuple(float(value) for value in angles),
        positions=tuple(float(value) for value in positions),
        canonical_size=(args.rectified_width, rectified_height),
        source_roi=SourceRoi(
            args.source_roi_x,
            args.source_roi_y,
            args.source_roi_width,
            args.source_roi_height,
        ),
        camera_mode=CameraMode(
            device=args.camera,
            width=args.width,
            height=args.height,
            fps=args.fps,
            fourcc=args.camera_fourcc,
            buffer_size=args.camera_buffer_size,
            disable_dynamic_framerate=not args.allow_dynamic_framerate,
            exposure_time_absolute=args.exposure_time_absolute,
            read_timeout_seconds=args.camera_read_timeout_ms / 1000.0,
        ),
    )


def prepare_calibration_sample(
    frame: np.ndarray,
    *,
    angle_deg: float,
    positions: tuple[float, ...],
    canonical_size: tuple[int, int],
    source_roi: SourceRoi,
    corner_window: str,
    position_window: str,
    maximum_width: int,
    maximum_height: int,
) -> PreparedCalibrationSample:
    source_roi.validate_inside((frame.shape[1], frame.shape[0]))
    cropped = source_roi.crop(frame)
    corner_selection = select_points(
        cropped,
        window_name=corner_window,
        labels=("TL", "TR", "BR", "BL"),
        maximum_width=maximum_width,
        maximum_height=maximum_height,
    )
    corners = order_quad_points(corner_selection.image_points)
    homography = compute_homography(corners, canonical_size)
    rectified = cv2.warpPerspective(
        cropped,
        homography,
        canonical_size,
        flags=cv2.INTER_LINEAR,
    )
    position_selection = select_points(
        rectified,
        window_name=position_window,
        labels=tuple(f"{value:+g}cm" for value in positions),
        maximum_width=maximum_width,
        maximum_height=maximum_height,
    )
    coefficients = fit_position_polynomial(
        [point[0] for point in position_selection.image_points],
        positions,
        output_width=canonical_size[0],
    )
    return PreparedCalibrationSample(
        sample=AngleCalibrationSample(
            angle_deg=angle_deg,
            source_corners_px=corners,
            position_coefficients=coefficients,
        ),
        source_preview=draw_source_preview(cropped, corners, angle_deg),
        rectified_preview=draw_rectified_preview(
            rectified,
            position_selection.image_points,
            positions,
        ),
    )


def save_calibration_previews(
    output_dir: Path,
    stem: str,
    prepared: PreparedCalibrationSample,
) -> None:
    if not cv2.imwrite(
        str(output_dir / f"{stem}_source.png"),
        prepared.source_preview,
    ):
        raise RuntimeIOError("保存标定源图失败")
    if not cv2.imwrite(
        str(output_dir / f"{stem}_rectified.png"),
        prepared.rectified_preview,
    ):
        raise RuntimeIOError("保存标定展开图失败")
