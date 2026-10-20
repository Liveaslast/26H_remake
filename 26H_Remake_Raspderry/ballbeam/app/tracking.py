"""Construct the camera, calibration, detector and tracker.

管理逐帧视觉循环
    1. 取图
    2. 查询角度
    3. 调用跟踪器
    4. 交出结果
    5. 按配置显示画面
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import time
from typing import Callable

import numpy as np

from .detector_setup import load_detector
from ..errors import RuntimeIOError
from ..hardware.camera import CameraMode, FixedUSBCamera
from ..interfaces.presentation import TrackingDisplay, VisionReporter
from ..vision.angles import FrameAngle
from ..vision.calibration import (
    DynamicCalibration, DynamicCalibrationError, SourceRoi, require_matching_source_roi,
)
from ..vision.metrics import VisionStats
from ..vision.tracker import DynamicBallTracker, DynamicTrackerConfig, DynamicTrackingResult


@dataclass(frozen=True, slots=True)
class TrackingComponents:
    calibration: DynamicCalibration
    tracker: DynamicBallTracker
    camera: FixedUSBCamera

"""
搭建视觉系统，并返回三个对象供外部调用：
    1. 视觉标定：
        从标定文件加载动态标定数据，并检查相机分辨率、ROI 和标定配置是否匹配。
    2. 小球跟踪器：
        调用 load_detector() 加载 YOLO 检测器，并把检测器、标定数据及跟踪参数交给 DynamicBallTracker
    3. 相机对象
        根据参数创建相机对象，保存设备编号、分辨率、FPS、曝光时间等配置。

"""
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


# 暂时看不懂的回调声明
AngleForFrame = Callable[[float], FrameAngle]
BeforeCapture = Callable[[], None]
FallbackOverlay = Callable[
    [np.ndarray, DynamicTrackingResult, float | None],
    np.ndarray,
]
DecorateOverlay = Callable[[np.ndarray, FrameAngle, float | None], np.ndarray]
KeyHandler = Callable[[int], None]
ResultHandler = Callable[[DynamicTrackingResult], None]
FrameHandler = Callable[[np.ndarray], None]

## 图像处理器： 调用跟踪器处理图像
def process_frame(tracker, frame, timestamp, decision):
    """Run one vision step; translate unavailable geometry into an invalid result."""
    if decision.angle_deg is None:
        return tracker.process_missing_angle(timestamp, decision.invalid_reason)
    try:
        return tracker.process(frame, decision.angle_deg, timestamp)
    except DynamicCalibrationError as exc:
        return tracker.process_missing_angle(timestamp, f"rectification-invalid:{exc}")

## 管理相机启动、逐帧循环、结果交付和画面显示
def run_tracking_loop(
    components: TrackingComponents,
    args,
    *,
    angle_for_frame: AngleForFrame,
    window_name: str,
    before_capture: BeforeCapture | None = None,
    fallback_overlay: FallbackOverlay | None = None,
    decorate_overlay: DecorateOverlay | None = None,
    key_handler: KeyHandler | None = None,
    result_handler: ResultHandler | None = None,
    frame_handler: FrameHandler | None = None,
    hold_last_display_on_missing: bool = False,
) -> int:
    """Run the shared latest-frame loop without owning an angle source."""

    camera = components.camera
    tracker = components.tracker
    started = time.perf_counter()
    finish_at = None if args.duration == 0 else started + args.duration
    statistics = VisionStats(window_seconds=1.0)
    reporter = VisionReporter(args.report_period)
    display = TrackingDisplay(
        window_name, enabled=not args.no_display,
        fallback_overlay=fallback_overlay, decorate_overlay=decorate_overlay,
        key_handler=key_handler, hold_last=hold_last_display_on_missing,
    )

    camera.open()
    try:
        camera.warm_up(args.warmup_frames)
        while finish_at is None or time.perf_counter() < finish_at:     # 视觉数据 -> 客户端 的循环
            if before_capture is not None:
                before_capture()
            frame, timestamp = camera.read()                            # 读取相机图像 ，获得图像以及时间戳
            decision = angle_for_frame(timestamp)                       # 获取图像对应的电机角度

            result = process_frame(tracker, frame, timestamp, decision) # 根据电机角度，调用跟踪器处理当前图像

            if result_handler is not None:                              # 判断是否有回调：handle_result
                result_handler(result)                                  # 把视觉结果交给客户端
            if frame_handler is not None:                               # 判断是否有回调：stream.publish
                frame_handler(frame)                                    # 把帧交给客户端（供图传）

            now = time.perf_counter()
            metrics = statistics.update(now, result)
            reporter.report(now, result, decision, metrics)
            if not display.show(frame, result, decision, metrics.fps):
                break
        return 0
    finally:
        try:
            camera.close()
        finally:
            display.close()
