"""
电机角度历史记录器:
    保存STM32回传的电机角度及Pi接收时间，供视觉查询
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import threading
import time
from typing import Any

@dataclass(frozen=True, slots=True)
class AngleReading:                 # 数据容器
    angle_deg: float                # 电机角度
    received_monotonic: float       # Pi接收时刻；插值结果使用目标时刻（秒）
    age_seconds: float              # 查询时刻与所用实测记录的时间差（秒）

"""
电机角度插值估计器：
    估计图像对应的电机角度
"""
def interpolate_angle_samples(
    history: tuple[tuple[float, float], ...],
    target_monotonic: float,
    maximum_age_seconds: float,
) -> AngleReading | None:
    """在按时间升序的 ``(timestamp, angle)`` 样本中插值角度。"""

    target = float(target_monotonic)
    maximum_age = float(maximum_age_seconds)
    if maximum_age <= 0:
        raise ValueError("maximum_age_seconds 必须为正数")
    if not history:
        return None

    before: tuple[float, float] | None = None
    after: tuple[float, float] | None = None
    for sample in history:
        if sample[0] <= target:
            before = sample
        elif after is None:
            after = sample
            break

    if before is not None and after is not None:
        span = after[0] - before[0]
        nearest_age = min(target - before[0], after[0] - target)
        if span > 1e-9 and max(target - before[0], after[0] - target) <= maximum_age:
            ratio = (target - before[0]) / span
            angle = before[1] + ratio * (after[1] - before[1])
            return AngleReading(
                angle_deg=float(angle),
                received_monotonic=target,
                age_seconds=float(nearest_age),
            )

    nearest = min((sample for sample in (before, after) if sample is not None),
                  key=lambda sample: abs(target - sample[0]), default=None)
    if nearest is None:
        return None
    age = abs(target - nearest[0])
    if age > maximum_age:
        return None
    return AngleReading(
        angle_deg=float(nearest[1]),
        received_monotonic=float(nearest[0]),
        age_seconds=float(age),
    )

"""
角度历史管理器：
    保存一段角度历史并提供查询接口
"""
class AngleHistory:
    """Store and query motor angles; no communication client or device lifecycle."""

    def __init__(                                           # 创建角度历史存放队列和访问锁
        self,
        history_samples: int = 256,
    ) -> None:
        if history_samples < 2:
            raise ValueError("角度历史样本数必须至少为2")
        self._history: deque[tuple[float, float]] = deque(maxlen=history_samples)
        self._history_lock = threading.Lock()

    def record(self, telemetry: Any) -> None:               # 提取角度及接收时间，并入列
        angle = float(telemetry.actual_angle_deg)
        received = float(telemetry.received_monotonic)
        if not math.isfinite(angle) or not math.isfinite(received):
            return
        with self._history_lock:
            self._history.append((received, angle))

    def latest(                                             # 最新值查询
        self,
        *,
        maximum_age_seconds: float,
        now: float | None = None,
    ) -> AngleReading | None:
        current = time.perf_counter() if now is None else float(now)
        with self._history_lock:
            if not self._history:
                return None
            received, angle = self._history[-1]
        age = max(0.0, current - received)
        if age > maximum_age_seconds:
            return None
        return AngleReading(
            angle_deg=angle,
            received_monotonic=received,
            age_seconds=age,
        )

    def angle_at(                                           # 指定时刻查询
        self,
        target_monotonic: float,
        *,
        maximum_age_seconds: float,
    ) -> AngleReading | None:
        """用相邻遥测插值得到指定相机时间戳对应的实际角度。"""

        target = float(target_monotonic)
        with self._history_lock:
            history = tuple(self._history)
        return interpolate_angle_samples(
            history,
            target,
            maximum_age_seconds,
        )


"""
给每张图像匹配上电机角度信息
"""



@dataclass(frozen=True, slots=True)
class FrameAngle:                                       ## 结果容器
    angle_deg: float | None                                 ## 电机角度
    invalid_reason: str = "angle-missing"                   ## 无效原因
    report_prefix: str = ""                                 ## 提示文字

"""
图像-电机角度匹配器
"""
class FrameAngleSource:
    def __init__(self, angles, *, maximum_age_seconds, camera_latency_seconds,
                 calibration_range, clamp):
        self.angles = angles                                            ## AngleHistory 对象，调用它查询角度
        self.maximum_age = maximum_age_seconds                          ## 允许图像目标时刻与角度记录时刻相差多久
        self.camera_latency = camera_latency_seconds                    ## 从图像读取时间中减去的估计相机延迟（从摄像机获取信号到生成图片有段时间延迟）
        self.minimum, self.maximum = calibration_range                  ## 标定角度的最小值、最大值
        self.clamp = clamp                                              ## 判断是否把越界角度限制到标定范围

    def for_frame(self, captured_monotonic: float) -> FrameAngle:       ##  为一张图像匹配电机角度
        angle_timestamp = captured_monotonic - self.camera_latency
        angle = self.angles.angle_at(
            angle_timestamp,
            maximum_age_seconds=self.maximum_age,
        )
        if angle is None:
            return FrameAngle(
                angle_deg=None,
                invalid_reason="angle-telemetry-stale",
            )
        actual_angle = angle.angle_deg
        if self.clamp:
            clamped_angle = min(
                max(actual_angle, self.minimum),
                self.maximum,
            )
            if clamped_angle != actual_angle:
                return FrameAngle(
                    angle_deg=clamped_angle,
                    report_prefix=(
                        f"angle-clamped raw={actual_angle:+.3f}deg "
                        f"used={clamped_angle:+.3f}deg "
                    ),
                )
        return FrameAngle(angle_deg=actual_angle)
