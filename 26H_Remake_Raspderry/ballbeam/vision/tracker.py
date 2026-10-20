"""视觉处理链：展开、检测、候选选择、时序状态和结果交付。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Literal, Protocol

import numpy as np

from .calibration import (
    DynamicCalibration,
    RectificationState,
)
from .estimator import ConstantVelocityKalman, FirstOrderLowPass


TrackingSource = Literal["ransac", "yolo_box", "prediction", "none"]


class DetectorProtocol(Protocol):
    def detect(self, frame: np.ndarray) -> Any:
        """返回含 ``balls``、``inference_ms``、``refinement_ms`` 的对象。"""


@dataclass(frozen=True, slots=True)
class DynamicTrackerConfig:
    """动态检测、数据关联和滤波参数。"""

    enable_kalman: bool = False
    minimum_confidence: float = 0.25
    vertical_band_min: float = 0.05
    vertical_band_max: float = 0.95
    minimum_radius_px: float = 2.0
    maximum_radius_height_ratio: float = 0.60
    association_gate_cm: float = 3.5
    physical_range_margin_cm: float = 1.5
    maximum_lost_seconds: float = 0.10
    reset_after_seconds: float = 0.50
    confirmation_hits: int = 2
    measurement_center: Literal["refined", "bbox"] = "refined"
    process_acceleration_std_cm_s2: float = 40.0
    kalman_initial_position_std_cm: float = 0.20
    kalman_initial_velocity_std_cm_s: float = 20.0
    kalman_minimum_dt_seconds: float = 1e-4
    kalman_maximum_dt_seconds: float = 0.10
    ransac_measurement_std_cm: float = 0.08
    yolo_measurement_std_cm: float = 0.18
    refinement_score_bonus: float = 0.08
    association_distance_penalty: float = 0.20
    velocity_lowpass_tau_seconds: float = 0.0
    gravity_model_gain: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence 必须在 [0, 1] 内")
        if not (
            0.0 <= self.vertical_band_min
            < self.vertical_band_max
            <= 1.0
        ):
            raise ValueError("凹槽纵向中心带比例无效")
        if self.minimum_radius_px <= 0:
            raise ValueError("minimum_radius_px 必须为正数")
        if not 0 < self.maximum_radius_height_ratio <= 1.0:
            raise ValueError("maximum_radius_height_ratio 必须在 (0, 1] 内")
        if self.association_gate_cm <= 0:
            raise ValueError("association_gate_cm 必须为正数")
        if self.physical_range_margin_cm < 0:
            raise ValueError("physical_range_margin_cm 不能为负数")
        if self.maximum_lost_seconds <= 0:
            raise ValueError("maximum_lost_seconds 必须为正数")
        if self.reset_after_seconds <= self.maximum_lost_seconds:
            raise ValueError("reset_after_seconds 必须大于 maximum_lost_seconds")
        if self.confirmation_hits < 1:
            raise ValueError("confirmation_hits 必须至少为 1")
        if self.measurement_center not in {"refined", "bbox"}:
            raise ValueError("measurement_center 必须是 refined 或 bbox")
        if self.process_acceleration_std_cm_s2 <= 0:
            raise ValueError("过程加速度标准差必须为正数")
        kalman_values = (
            self.kalman_initial_position_std_cm,
            self.kalman_initial_velocity_std_cm_s,
            self.kalman_minimum_dt_seconds,
            self.kalman_maximum_dt_seconds,
        )
        if min(kalman_values) <= 0:
            raise ValueError("Kalman初始标准差和时间步长必须为正数")
        if self.kalman_maximum_dt_seconds < self.kalman_minimum_dt_seconds:
            raise ValueError("Kalman最大时间步长不能小于最小时间步长")
        if min(
            self.ransac_measurement_std_cm,
            self.yolo_measurement_std_cm,
        ) <= 0:
            raise ValueError("测量标准差必须为正数")
        if min(self.refinement_score_bonus, self.association_distance_penalty) < 0:
            raise ValueError("候选评分权重不能为负数")
        if (
            not math.isfinite(self.velocity_lowpass_tau_seconds)
            or self.velocity_lowpass_tau_seconds < 0
        ):
            raise ValueError("速度低通时间常数必须是有限非负数")
        if not math.isfinite(self.gravity_model_gain):
            raise ValueError("gravity_model_gain 必须是有限数值")


@dataclass(frozen=True, slots=True)
class DynamicTrackingResult:
    """每一帧交给控制器和调试画面的跟踪结果。"""

    timestamp: float
    position_cm: float | None
    velocity_cm_s: float | None
    actual_angle_deg: float | None
    measurement_valid: bool
    tracking_valid: bool
    source: TrackingSource
    confidence: float
    lost_seconds: float | None
    reason: str
    center_px: tuple[float, float] | None = None
    radius_px: float | None = None
    box_xyxy: tuple[float, float, float, float] | None = None
    measurement_position_cm: float | None = None
    rectified: np.ndarray | None = None
    rectification: RectificationState | None = None
    inference_ms: float = 0.0
    refinement_ms: float = 0.0
    processing_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class BallMeasurement:
    detection: Any
    position_cm: float
    score: float
    center_px: tuple[float, float]
    source: TrackingSource
    radius_px: float


class CandidateSelector:
    """Select one physical ball measurement from pixel-space detections."""

    def __init__(self, calibration, config):
        self.calibration = calibration
        self.config = config

    def _position_limits(
        self,
        state: RectificationState,
    ) -> tuple[float, float]:
        width = self.calibration.canonical_size[0]
        endpoints = (
            state.pixel_to_cm(0.0),
            state.pixel_to_cm(float(width - 1)),
        )
        low, high = sorted(endpoints)
        margin = self.config.physical_range_margin_cm
        return low - margin, high + margin

    def select(
        self,
        detections: Any,
        state: RectificationState,
        *,
        predicted_position: float | None = None,
        lost_seconds: float | None = None,
    ) -> BallMeasurement | None:
        height = self.calibration.canonical_size[1]
        y_low = self.config.vertical_band_min * height
        y_high = self.config.vertical_band_max * height
        radius_max = self.config.maximum_radius_height_ratio * height
        position_low, position_high = self._position_limits(state)
        predicted = predicted_position
        lost = lost_seconds
        use_prediction_gate = (
            predicted is not None
            and lost is not None
            and lost <= self.config.maximum_lost_seconds
        )

        candidates: list[BallMeasurement] = []
        for detection in getattr(detections, "balls", ()):
            confidence = float(getattr(detection, "confidence", 0.0))
            if (
                not math.isfinite(confidence)
                or confidence < self.config.minimum_confidence
            ):
                continue
            center = self._measurement_center_px(detection)
            if center is None or len(center) != 2:
                continue
            u, v = map(float, center)
            radius = self._measurement_radius_px(detection)
            if not all(math.isfinite(value) for value in (u, v, radius)):
                continue
            if not (y_low <= v <= y_high):
                continue
            if not self.config.minimum_radius_px <= radius <= radius_max:
                continue

            position = state.pixel_to_cm(u)
            if not position_low <= position <= position_high:
                continue
            distance = (
                0.0 if predicted is None else abs(position - predicted)
            )
            if use_prediction_gate and distance > self.config.association_gate_cm:
                continue

            source = str(getattr(detection, "source", "yolo_box"))
            measurement_source: TrackingSource = (
                "yolo_box"
                if self.config.measurement_center == "bbox"
                else "ransac"
                if source in {"ransac", "cached_ransac"}
                else "yolo_box"
            )
            refinement_bonus = (
                self.config.refinement_score_bonus
                if measurement_source == "ransac"
                else 0.0
            )
            distance_penalty = (
                0.0
                if predicted is None
                else self.config.association_distance_penalty * min(
                    1.0,
                    distance / self.config.association_gate_cm,
                )
            )
            candidates.append(
                BallMeasurement(
                    detection=detection,
                    position_cm=position,
                    score=confidence + refinement_bonus - distance_penalty,
                    center_px=(u, v),
                    source=measurement_source,
                    radius_px=radius,
                )
            )

        if not candidates:
            return None
        return max(candidates, key=lambda candidate: candidate.score)

    def _measurement_center_px(self, detection: Any) -> tuple[float, float] | None:
        if self.config.measurement_center == "bbox":
            box = getattr(detection, "box_xyxy", None)
            if box is not None and len(box) == 4:
                x1, y1, x2, y2 = map(float, box)
                if all(math.isfinite(value) for value in (x1, y1, x2, y2)):
                    return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)
        center = getattr(detection, "center_px", None)
        if center is None or len(center) != 2:
            return None
        u, v = map(float, center)
        return (u, v)

    def _measurement_radius_px(self, detection: Any) -> float:
        if self.config.measurement_center == "bbox":
            box = getattr(detection, "box_xyxy", None)
            if box is not None and len(box) == 4:
                x1, y1, x2, y2 = map(float, box)
                if all(math.isfinite(value) for value in (x1, y1, x2, y2)):
                    return max(0.0, min(abs(x2 - x1), abs(y2 - y1)) * 0.5)
        return float(getattr(detection, "radius_px", 0.0))


@dataclass(frozen=True, slots=True)
class TrackingStatus:
    position_cm: float | None
    velocity_cm_s: float | None
    tracking_valid: bool
    lost_seconds: float | None
    source: TrackingSource
    reason: str


class TrackingState:
    """Own confirmation, loss history and the existing optional state estimator."""

    def __init__(self, config):
        self.config = config
        self.kalman = (
            ConstantVelocityKalman(
                config.process_acceleration_std_cm_s2,
                initial_position_std_cm=config.kalman_initial_position_std_cm,
                initial_velocity_std_cm_s=config.kalman_initial_velocity_std_cm_s,
                minimum_dt_seconds=config.kalman_minimum_dt_seconds,
                maximum_dt_seconds=config.kalman_maximum_dt_seconds,
            ) if config.enable_kalman else None
        )
        self.velocity_lowpass = (
            FirstOrderLowPass(config.velocity_lowpass_tau_seconds)
            if config.enable_kalman else None
        )
        self.reset()

    def reset(self):
        if self.kalman is not None:
            self.kalman.reset()
            self.velocity_lowpass.reset()
        self._last_measurement_timestamp = None
        self._consecutive_hits = 0
        self._confirmed = False
        self._last_result_timestamp = None

    def begin_frame(self, timestamp):
        if self._last_result_timestamp is not None and timestamp < self._last_result_timestamp - 1e-9:
            raise ValueError("输入帧时间戳不能倒退")
        self._last_result_timestamp = timestamp

    @property
    def predicted_position(self):
        return self.kalman.position_cm if self.kalman is not None else None

    def lost_seconds(self, timestamp):
        if self._last_measurement_timestamp is None:
            return None
        return max(0.0, timestamp - self._last_measurement_timestamp)

    def predict(self, timestamp, angle_deg=None):
        if self.kalman is not None:
            acceleration = 0.0 if angle_deg is None else self._acceleration_from_angle(angle_deg)
            self.kalman.predict(timestamp, acceleration)

    def _acceleration_from_angle(self, angle_deg):
        # gain 的符号取决于角度和 x 轴定义，默认 0 表示关闭。理论纯滚动
        # 实心球可从约 5/7 开始在台架上辨识。
        return self.config.gravity_model_gain * 980.665 * math.sin(math.radians(float(angle_deg)))

    def _velocity(self, timestamp):
        if self.kalman is None:
            return 0.0
        velocity = self.kalman.velocity_cm_s
        if velocity is None:
            self.velocity_lowpass.reset()
            return None
        return self.velocity_lowpass.update(velocity, timestamp)

    def _reset_stale_estimate(self, timestamp, lost):
        if self.kalman is not None and lost is not None and lost > self.config.reset_after_seconds:
            self.kalman.reset(timestamp=timestamp)
            self.velocity_lowpass.reset()
            self._confirmed = False

    def observe(self, measurement, timestamp):
        if measurement is None:
            self._consecutive_hits = 0
            lost = self.lost_seconds(timestamp)
            valid = self._confirmed and lost is not None and lost <= self.config.maximum_lost_seconds
            self._reset_stale_estimate(timestamp, lost)
            if self.kalman is not None and lost is not None and lost > self.config.reset_after_seconds:
                valid = False
            return TrackingStatus(self.predicted_position, self._velocity(timestamp), valid,
                                  lost, "prediction" if valid else "none",
                                  "short-prediction" if valid else "ball-not-detected")

        if self.kalman is not None:
            lost = self.lost_seconds(timestamp)
            if lost is not None and lost > self.config.reset_after_seconds:
                self.kalman.reset(measurement.position_cm, timestamp)
                self.velocity_lowpass.reset()
                self._consecutive_hits = 1
                self._confirmed = self.config.confirmation_hits == 1
            else:
                source = str(getattr(measurement.detection, "source", "yolo_box"))
                base_std = (self.config.ransac_measurement_std_cm
                            if source in {"ransac", "cached_ransac"} else self.config.yolo_measurement_std_cm)
                confidence = max(self.config.minimum_confidence,
                                 float(getattr(measurement.detection, "confidence", 0.0)))
                self.kalman.update(measurement.position_cm, base_std / math.sqrt(confidence))
                self._consecutive_hits += 1
                if self._consecutive_hits >= self.config.confirmation_hits:
                    self._confirmed = True
            position, velocity = self.predicted_position, self._velocity(timestamp)
        else:
            self._consecutive_hits += 1
            if self._consecutive_hits >= self.config.confirmation_hits:
                self._confirmed = True
            position, velocity = measurement.position_cm, 0.0
        self._last_measurement_timestamp = timestamp
        return TrackingStatus(position, velocity, self._confirmed, 0.0, measurement.source,
                              "ok" if self._confirmed else "waiting-for-confirmation")

    def missing_angle(self, timestamp, reason):
        self.predict(timestamp)
        lost = self.lost_seconds(timestamp)
        self._reset_stale_estimate(timestamp, lost)
        self._consecutive_hits = 0
        self._last_result_timestamp = timestamp
        return TrackingStatus(self.predicted_position, self._velocity(timestamp), False, lost, "none", reason)


class DynamicBallTracker:
    """Coordinate geometry, detector, measurement selection and tracking state."""

    def __init__(self, calibration: DynamicCalibration, detector: DetectorProtocol,
                 config: DynamicTrackerConfig | None = None, *, selector=None, state=None):
        self.calibration = calibration
        self.detector = detector
        self.config = config or DynamicTrackerConfig()
        self.selector = selector if selector is not None else CandidateSelector(calibration, self.config)
        self.state = state if state is not None else TrackingState(self.config)

    def reset(self):
        self.state.reset()

    def process(self, frame: np.ndarray, actual_angle_deg: float, timestamp: float) -> DynamicTrackingResult:
        started = time.perf_counter()
        current = float(timestamp)
        self.state.begin_frame(current)
        rectified, geometry = self.calibration.rectify(frame, actual_angle_deg)
        self.state.predict(current, actual_angle_deg)
        detections = self.detector.detect(rectified)
        measurement = self.selector.select(
            detections, geometry, predicted_position=self.state.predicted_position,
            lost_seconds=self.state.lost_seconds(current),
        )
        status = self.state.observe(measurement, current)
        return DynamicTrackingResult(
            timestamp=current, position_cm=status.position_cm, velocity_cm_s=status.velocity_cm_s,
            actual_angle_deg=float(actual_angle_deg), measurement_valid=measurement is not None,
            tracking_valid=status.tracking_valid, source=status.source,
            confidence=float(getattr(measurement.detection, "confidence", 0.0)) if measurement else 0.0,
            lost_seconds=status.lost_seconds, reason=status.reason,
            center_px=measurement.center_px if measurement else None,
            radius_px=measurement.radius_px if measurement else None,
            box_xyxy=tuple(map(float, measurement.detection.box_xyxy)) if measurement else None,
            measurement_position_cm=measurement.position_cm if measurement else None,
            rectified=rectified, rectification=geometry,
            inference_ms=float(getattr(detections, "inference_ms", 0.0)),
            refinement_ms=float(getattr(detections, "refinement_ms", 0.0)),
            processing_ms=(time.perf_counter() - started) * 1000.0,
        )

    def process_missing_angle(self, timestamp: float, reason: str = "angle-telemetry-stale") -> DynamicTrackingResult:
        """角度遥测无效时立即阻止结果进入控制器。"""
        current = float(timestamp)
        status = self.state.missing_angle(current, reason)
        return DynamicTrackingResult(
            timestamp=current, position_cm=status.position_cm, velocity_cm_s=status.velocity_cm_s,
            actual_angle_deg=None, measurement_valid=False, tracking_valid=status.tracking_valid,
            source=status.source, confidence=0.0, lost_seconds=status.lost_seconds, reason=status.reason,
        )
