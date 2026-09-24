"""Safe outer-loop controller for ball position to rod target angle."""

from __future__ import annotations

from dataclasses import dataclass
import math

from ..vision.tracker import DynamicTrackingResult


@dataclass(frozen=True, slots=True)
class BalanceControllerConfig:
    """Units: cm, cm/s, degrees, and seconds."""

    target_position_cm: float = 0.0
    kp_deg_per_cm: float = 0.0
    kd_deg_per_cm_s: float = 0.0
    ki_deg_per_cm_s: float = 0.0
    maximum_angle_deg: float = 5.0
    maximum_slew_deg_s: float = 30.0
    invalid_return_deg_s: float = 15.0
    integral_limit_cm_s: float = 20.0
    maximum_step_seconds: float = 0.10

    def __post_init__(self) -> None:
        values = (
            self.target_position_cm,
            self.kp_deg_per_cm,
            self.kd_deg_per_cm_s,
            self.ki_deg_per_cm_s,
            self.maximum_angle_deg,
            self.maximum_slew_deg_s,
            self.invalid_return_deg_s,
            self.integral_limit_cm_s,
            self.maximum_step_seconds,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("控制器参数必须是有限数值")
        if min(
            self.maximum_angle_deg,
            self.maximum_slew_deg_s,
            self.invalid_return_deg_s,
            self.integral_limit_cm_s,
            self.maximum_step_seconds,
        ) <= 0:
            raise ValueError("控制器限幅、变化率和积分限幅必须为正数")


@dataclass(frozen=True, slots=True)
class BalanceCommand:
    ball_position_cm: float
    ball_velocity_cm_s: float
    target_angle_deg: float
    tracking_valid: bool
    enable: bool


class BalanceController:
    """Compute a rate-limited rod target and a safe invalid-state command."""

    def __init__(
        self,
        config: BalanceControllerConfig,
        *,
        actuator_enabled: bool,
    ) -> None:
        self.config = config
        self.actuator_enabled = bool(actuator_enabled)
        self._last_timestamp: float | None = None
        self._last_target_angle_deg = 0.0
        self._integral_error_cm_s = 0.0
        self._last_position_cm = 0.0
        self._last_velocity_cm_s = 0.0

    def reset(self) -> None:
        self._last_timestamp = None
        self._last_target_angle_deg = 0.0
        self._integral_error_cm_s = 0.0
        self._last_position_cm = 0.0
        self._last_velocity_cm_s = 0.0

    def update(self, result: DynamicTrackingResult) -> BalanceCommand:
        timestamp = float(result.timestamp)
        if not math.isfinite(timestamp):
            raise ValueError("跟踪结果时间戳必须是有限数值")

        dt = self._step_seconds(timestamp)
        valid = bool(
            result.tracking_valid
            and result.position_cm is not None
            and result.velocity_cm_s is not None
            and math.isfinite(result.position_cm)
            and math.isfinite(result.velocity_cm_s)
        )

        if valid:
            position = float(result.position_cm)
            velocity = float(result.velocity_cm_s)
            self._last_position_cm = position
            self._last_velocity_cm_s = velocity
            error = self.config.target_position_cm - position
            if dt > 0:
                self._integral_error_cm_s = self._clip(
                    self._integral_error_cm_s + error * dt,
                    self.config.integral_limit_cm_s,
                )
            desired = (
                self.config.kp_deg_per_cm * error
                - self.config.kd_deg_per_cm_s * velocity
                + self.config.ki_deg_per_cm_s
                * self._integral_error_cm_s
            )
            desired = self._clip(
                desired,
                self.config.maximum_angle_deg,
            )
            rate = self.config.maximum_slew_deg_s
        else:
            position = self._last_position_cm
            velocity = self._last_velocity_cm_s
            self._integral_error_cm_s = 0.0
            desired = 0.0
            rate = self.config.invalid_return_deg_s

        target_angle = self._move_toward(
            self._last_target_angle_deg,
            desired,
            rate * dt,
        )
        self._last_target_angle_deg = target_angle
        return BalanceCommand(
            ball_position_cm=position,
            ball_velocity_cm_s=velocity,
            target_angle_deg=target_angle,
            tracking_valid=valid,
            enable=self.actuator_enabled,
        )

    def _step_seconds(self, timestamp: float) -> float:
        previous = self._last_timestamp
        self._last_timestamp = timestamp
        if previous is None or timestamp <= previous:
            return 0.0
        return min(timestamp - previous, self.config.maximum_step_seconds)

    @staticmethod
    def _clip(value: float, limit: float) -> float:
        return max(-limit, min(limit, value))

    @staticmethod
    def _move_toward(current: float, target: float, step: float) -> float:
        if step <= 0:
            return current
        delta = target - current
        if abs(delta) <= step:
            return target
        return current + math.copysign(step, delta)
