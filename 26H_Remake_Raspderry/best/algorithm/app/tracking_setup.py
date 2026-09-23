"""Shared CLI validation and component construction for tracking applications."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path

from .tracking_support import (
    add_detector_performance_arguments,
    load_detector,
)
from .vision_geometry import (
    add_source_roi_arguments,
    require_matching_source_roi,
    source_roi_from_args,
)
from ..core.calibration import DynamicCalibration, SourceRoi
from ..core.tracker import DynamicBallTracker, DynamicTrackerConfig
from ..io.runtime import CameraMode, FixedUSBCamera, RuntimeIOError


@dataclass(frozen=True, slots=True)
class TrackingComponents:
    calibration: DynamicCalibration
    tracker: DynamicBallTracker
    camera: FixedUSBCamera


def add_common_tracking_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Declare parameters shared by formal and no-M0 tracking applications.

    Defaults are intentionally supplied by ``algorithm/config.toml`` instead
    of being duplicated here.
    """

    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument(
        "--image-size",
        type=int,
        help="0表示从NCNN metadata.yaml自动读取（默认：0）",
    )
    parser.add_argument("--model-width", type=int)
    parser.add_argument("--model-height", type=int)
    parser.add_argument("--confidence", type=float)
    parser.add_argument("--iou", type=float)
    parser.add_argument("--max-detections", type=int)
    add_detector_performance_arguments(parser)
    parser.add_argument("--camera")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--fps", type=float)
    parser.add_argument("--camera-fourcc")
    parser.add_argument("--camera-buffer-size", type=int)
    parser.add_argument("--camera-read-timeout-ms", type=float)
    parser.add_argument(
        "--exposure-time-absolute",
        type=int,
        help="UVC exposure in 100us units; use a short fixed value for motion",
    )
    parser.add_argument("--allow-dynamic-framerate", action="store_true")
    parser.add_argument(
        "--lock-dynamic-framerate",
        dest="allow_dynamic_framerate",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--warmup-frames", type=int)
    parser.add_argument(
        "--skip-detector-warmup",
        action="store_true",
        help="skip the model warmup inference before opening camera/serial",
    )
    parser.add_argument("--maximum-lost-ms", type=float)
    parser.add_argument("--reset-after-ms", type=float)
    parser.add_argument("--confirmation-hits", type=int)
    parser.add_argument(
        "--measurement-center",
        choices=("refined", "bbox"),
        help="refined uses RANSAC/cached circle center; bbox uses YOLO box center",
    )
    parser.add_argument("--association-gate-cm", type=float)
    parser.add_argument("--physical-range-margin-cm", type=float)
    parser.add_argument("--minimum-radius-px", type=float)
    parser.add_argument("--maximum-radius-height-ratio", type=float)
    parser.add_argument("--ransac-measurement-std-cm", type=float)
    parser.add_argument("--yolo-measurement-std-cm", type=float)
    parser.add_argument("--kalman-initial-position-std-cm", type=float)
    parser.add_argument("--kalman-initial-velocity-std-cm-s", type=float)
    parser.add_argument("--kalman-minimum-dt-ms", type=float)
    parser.add_argument("--kalman-maximum-dt-ms", type=float)
    parser.add_argument(
        "--enable-kalman",
        action="store_true",
        help="enable Raspberry Pi Kalman prediction/filtering; default sends raw measurements",
    )
    parser.add_argument("--refinement-score-bonus", type=float)
    parser.add_argument("--association-distance-penalty", type=float)
    parser.add_argument(
        "--process-acceleration-std",
        "--process-acceleration-std-cm-s2",
        dest="process_acceleration_std_cm_s2",
        type=float,
        help=(
            "Kalman process acceleration standard deviation in cm/s^2"
        ),
    )
    parser.add_argument(
        "--velocity-lowpass-tau-ms",
        type=float,
        help=(
            "Velocity output low-pass time constant in milliseconds; "
            "0 disables it"
        ),
    )
    parser.add_argument("--vertical-band-min", type=float)
    parser.add_argument("--vertical-band-max", type=float)
    parser.add_argument(
        "--duration",
        type=float,
        help="运行秒数，0表示运行到 Ctrl+C",
    )
    parser.add_argument("--report-period", type=float)
    parser.add_argument("--no-display", action="store_true")
    parser.add_argument(
        "--display",
        dest="no_display",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    add_source_roi_arguments(parser)


def validate_common_tracking_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
    if args.image_size < 0 or (
        args.image_size > 0 and args.image_size % 32 != 0
    ):
        parser.error("--image-size 必须为0或正的32倍数")
    if min(args.model_width, args.model_height) < 32 or (
        args.model_width % 32 or args.model_height % 32
    ):
        parser.error("模型输入宽高必须是至少32的32倍数")
    if not 0 <= args.confidence <= 1 or not 0 <= args.iou <= 1:
        parser.error("--confidence 和 --iou 必须在 [0,1] 内")
    if args.max_detections < 1:
        parser.error("--max-detections 必须至少为1")
    if args.inference_backend in ("hailo", "hailort") and args.hailo_model is None:
        parser.error("--inference-backend hailo/hailort 必须同时指定 --hailo-model")
    if args.ncnn_threads < 1:
        parser.error("--ncnn-threads must be at least 1")
    if args.detection_interval < 1:
        parser.error("--detection-interval must be at least 1")
    if args.refine_interval < 0:
        parser.error("--refine-interval cannot be negative")
    if not 0 < args.track_scale <= 1:
        parser.error("--track-scale must be within (0,1]")
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
        parser.error("--warmup-frames 不能为负数")
    if args.maximum_lost_ms <= 0:
        parser.error("--maximum-lost-ms 必须为正数")
    if args.reset_after_ms <= args.maximum_lost_ms:
        parser.error("--reset-after-ms 必须大于 --maximum-lost-ms")
    if args.confirmation_hits < 1:
        parser.error("--confirmation-hits 必须至少为1")
    if args.association_gate_cm <= 0:
        parser.error("--association-gate-cm 必须为正数")
    if args.physical_range_margin_cm < 0:
        parser.error("--physical-range-margin-cm不能为负数")
    if args.minimum_radius_px <= 0:
        parser.error("--minimum-radius-px必须为正数")
    if not 0 < args.maximum_radius_height_ratio <= 1:
        parser.error("--maximum-radius-height-ratio必须在(0,1]内")
    if min(args.ransac_measurement_std_cm, args.yolo_measurement_std_cm) <= 0:
        parser.error("测量标准差必须为正数")
    kalman_values = (
        args.kalman_initial_position_std_cm,
        args.kalman_initial_velocity_std_cm_s,
        args.kalman_minimum_dt_ms,
        args.kalman_maximum_dt_ms,
    )
    if min(kalman_values) <= 0:
        parser.error("Kalman初始标准差和时间步长必须为正数")
    if args.kalman_maximum_dt_ms < args.kalman_minimum_dt_ms:
        parser.error("--kalman-maximum-dt-ms不能小于--kalman-minimum-dt-ms")
    if min(args.refinement_score_bonus, args.association_distance_penalty) < 0:
        parser.error("候选评分权重不能为负数")
    if args.process_acceleration_std_cm_s2 <= 0:
        parser.error("--process-acceleration-std 必须为正数")
    if (
        not math.isfinite(args.velocity_lowpass_tau_ms)
        or args.velocity_lowpass_tau_ms < 0
    ):
        parser.error("--velocity-lowpass-tau-ms 必须是有限非负数")
    if not (
        0 <= args.vertical_band_min < args.vertical_band_max <= 1
    ):
        parser.error("纵向中心带比例无效")
    if args.duration < 0 or args.report_period <= 0:
        parser.error("运行时长不能为负，报告周期必须为正")
    source_roi_from_args(args, parser)


def build_tracking_components(
    args: argparse.Namespace,
    *,
    gravity_model_gain: float,
) -> TrackingComponents:
    calibration_path = args.calibration.expanduser().resolve()
    calibration = DynamicCalibration.load(calibration_path)
    if calibration.source_size is not None and calibration.source_size != (
        args.width,
        args.height,
    ):
        raise RuntimeIOError(
            f"命令行相机尺寸 {args.width}x{args.height} 与标定尺寸 "
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
    print(
        f"Calibration loaded: {calibration_path}; "
        f"rectified={calibration.canonical_size[0]}x"
        f"{calibration.canonical_size[1]}; "
        f"angles={calibration.angle_range_deg[0]:+.3f}.."
        f"{calibration.angle_range_deg[1]:+.3f}deg; "
        f"samples={len(calibration.samples)}",
        f"source_roi={configured_roi.xywh}; geometry={calibration.geometry_id[:12]}",
        flush=True,
    )

    detector = load_detector(
        args,
        calibration.canonical_size,
        calibration_geometry_id=calibration.geometry_id,
    )
    tracker = DynamicBallTracker(
        calibration,
        detector,
        DynamicTrackerConfig(
            enable_kalman=args.enable_kalman,
            minimum_confidence=args.confidence,
            vertical_band_min=args.vertical_band_min,
            vertical_band_max=args.vertical_band_max,
            minimum_radius_px=args.minimum_radius_px,
            maximum_radius_height_ratio=args.maximum_radius_height_ratio,
            association_gate_cm=args.association_gate_cm,
            physical_range_margin_cm=args.physical_range_margin_cm,
            maximum_lost_seconds=args.maximum_lost_ms / 1000.0,
            reset_after_seconds=args.reset_after_ms / 1000.0,
            confirmation_hits=args.confirmation_hits,
            measurement_center=args.measurement_center,
            process_acceleration_std_cm_s2=(
                args.process_acceleration_std_cm_s2
            ),
            kalman_initial_position_std_cm=(
                args.kalman_initial_position_std_cm
            ),
            kalman_initial_velocity_std_cm_s=(
                args.kalman_initial_velocity_std_cm_s
            ),
            kalman_minimum_dt_seconds=args.kalman_minimum_dt_ms / 1000.0,
            kalman_maximum_dt_seconds=args.kalman_maximum_dt_ms / 1000.0,
            velocity_lowpass_tau_seconds=(
                args.velocity_lowpass_tau_ms / 1000.0
            ),
            ransac_measurement_std_cm=args.ransac_measurement_std_cm,
            yolo_measurement_std_cm=args.yolo_measurement_std_cm,
            refinement_score_bonus=args.refinement_score_bonus,
            association_distance_penalty=args.association_distance_penalty,
            gravity_model_gain=gravity_model_gain,
        ),
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
    return TrackingComponents(
        calibration=calibration,
        tracker=tracker,
        camera=camera,
    )
