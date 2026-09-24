"""State estimators used by the one-dimensional ball tracker."""

from __future__ import annotations

import math

import numpy as np


class FirstOrderLowPass:
    """Timestamp-aware first-order low-pass filter with an optional bypass."""

    def __init__(self, tau_seconds: float) -> None:
        self.tau_seconds = float(tau_seconds)
        if not math.isfinite(self.tau_seconds) or self.tau_seconds < 0:
            raise ValueError("tau_seconds must be finite and non-negative")
        self.value: float | None = None
        self.last_timestamp: float | None = None

    def reset(self) -> None:
        self.value = None
        self.last_timestamp = None

    def update(self, value: float, timestamp: float) -> float:
        current_value = float(value)
        current_timestamp = float(timestamp)
        if not math.isfinite(current_value):
            raise ValueError("low-pass input must be finite")
        if not math.isfinite(current_timestamp):
            raise ValueError("low-pass timestamp must be finite")
        if (
            self.last_timestamp is not None
            and current_timestamp < self.last_timestamp - 1e-9
        ):
            raise ValueError("low-pass timestamp cannot move backwards")

        previous_timestamp = self.last_timestamp
        self.last_timestamp = current_timestamp
        if self.value is None or self.tau_seconds == 0:
            self.value = current_value
            return current_value

        assert previous_timestamp is not None
        dt = max(0.0, current_timestamp - previous_timestamp)
        alpha = -math.expm1(-dt / self.tau_seconds)
        self.value += alpha * (current_value - self.value)
        return self.value


class ConstantVelocityKalman:
    """带可选已知加速度输入的 ``[x, vx]`` 卡尔曼滤波器。"""

    def __init__(
        self,
        acceleration_std_cm_s2: float,
        *,
        initial_position_std_cm: float = 0.20,
        initial_velocity_std_cm_s: float = 20.0,
        minimum_dt_seconds: float = 1e-4,
        maximum_dt_seconds: float = 0.10,
    ) -> None:
        self.acceleration_std_cm_s2 = float(acceleration_std_cm_s2)
        self.initial_position_std_cm = float(initial_position_std_cm)
        self.initial_velocity_std_cm_s = float(initial_velocity_std_cm_s)
        self.minimum_dt_seconds = float(minimum_dt_seconds)
        self.maximum_dt_seconds = float(maximum_dt_seconds)
        values = (
            self.acceleration_std_cm_s2,
            self.initial_position_std_cm,
            self.initial_velocity_std_cm_s,
            self.minimum_dt_seconds,
            self.maximum_dt_seconds,
        )
        if min(values) <= 0 or not all(math.isfinite(value) for value in values):
            raise ValueError("Kalman标准差和时间步长必须是有限正数")
        if self.maximum_dt_seconds < self.minimum_dt_seconds:
            raise ValueError("Kalman最大时间步长不能小于最小时间步长")
        self.state = np.zeros((2, 1), dtype=np.float64)
        self.covariance = np.eye(2, dtype=np.float64)
        self.last_timestamp: float | None = None
        self.initialized = False

    def reset(
        self,
        position_cm: float | None = None,
        timestamp: float | None = None,
    ) -> None:
        self.state.fill(0.0)
        self.covariance = np.diag(
            (
                self.initial_position_std_cm**2,
                self.initial_velocity_std_cm_s**2,
            )
        ).astype(np.float64)
        self.last_timestamp = timestamp
        self.initialized = position_cm is not None
        if position_cm is not None:
            self.state[0, 0] = float(position_cm)

    def predict(self, timestamp: float, acceleration_cm_s2: float = 0.0) -> None:
        current = float(timestamp)
        if not math.isfinite(current):
            raise ValueError("timestamp 必须是有限数值")
        if self.last_timestamp is None:
            self.last_timestamp = current
            return
        raw_dt = current - self.last_timestamp
        if raw_dt < -1e-9:
            raise ValueError("timestamp 不能倒退")
        dt = min(
            max(raw_dt, self.minimum_dt_seconds),
            self.maximum_dt_seconds,
        )
        self.last_timestamp = current
        if not self.initialized:
            return

        transition = np.asarray(((1.0, dt), (0.0, 1.0)))
        control = np.asarray(((0.5 * dt * dt,), (dt,)))
        self.state = (
            transition @ self.state
            + control * float(acceleration_cm_s2)
        )
        process_variance = self.acceleration_std_cm_s2**2
        process_noise = process_variance * (control @ control.T)
        self.covariance = (
            transition @ self.covariance @ transition.T + process_noise
        )

    def update(self, position_cm: float, measurement_std_cm: float) -> None:
        measurement = float(position_cm)
        if not self.initialized:
            self.reset(measurement, self.last_timestamp)
            return
        observation = np.asarray(((1.0, 0.0),))
        projected_state = (observation @ self.state)[0, 0]
        innovation = measurement - float(projected_state)
        innovation_covariance = float(
            (observation @ self.covariance @ observation.T)[0, 0]
            + measurement_std_cm**2
        )
        gain = self.covariance @ observation.T / innovation_covariance
        self.state = self.state + gain * innovation
        identity = np.eye(2, dtype=np.float64)
        # Joseph 形式减少浮点误差导致的非正定。
        correction = identity - gain @ observation
        measurement_covariance = np.asarray(((measurement_std_cm**2,),))
        self.covariance = (
            correction @ self.covariance @ correction.T
            + gain @ measurement_covariance @ gain.T
        )

    @property
    def position_cm(self) -> float | None:
        return float(self.state[0, 0]) if self.initialized else None

    @property
    def velocity_cm_s(self) -> float | None:
        return float(self.state[1, 0]) if self.initialized else None
