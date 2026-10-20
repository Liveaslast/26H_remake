"""
统计帧率、有效检测结果频率、平均耗时
"""

from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class VisionStatsSnapshot:
    fps: float | None
    valid_detection_hz: float | None
    average_inference_ms: float | None
    average_processing_ms: float


# 视觉处理循环耗时统计
class VisionStats:
    def __init__(self, window_seconds=1.0, maximum_samples=512):
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("统计窗口必须是有限正数")
        if maximum_samples < 2:
            raise ValueError("统计样本容量必须至少为2")
        self.window_seconds = window_seconds
        self._events = deque(maxlen=maximum_samples)

    def update(self, now, result) -> VisionStatsSnapshot:
        if not math.isfinite(now):
            raise ValueError("统计时间戳必须是有限数值")
        if self._events and now <= self._events[-1][0]:
            self._events.clear()
        detected = bool(result.measurement_valid
                        and result.source in {"yolo_box", "ransac"}
                        and result.inference_ms > 0)
        self._events.append((now, detected, result.inference_ms, result.processing_ms))
        while len(self._events) > 1 and self._events[0][0] < now - self.window_seconds:
            self._events.popleft()
        return self._summarize()

    def _summarize(self):
        events = tuple(self._events)
        fps = detection_hz = None
        if len(events) >= 2:
            elapsed = events[-1][0] - events[0][0]
            fps = (len(events) - 1) / elapsed
            # Count interval endpoints after the first sample, like the FPS numerator.
            detection_hz = sum(detected for _, detected, _, _ in events[1:]) / elapsed
        # Include unsuccessful inference attempts, not just successful detections.
        inference_times = [ms for _, _, ms, _ in events if ms > 0]
        return VisionStatsSnapshot(
            fps=fps, valid_detection_hz=detection_hz,
            average_inference_ms=(sum(inference_times) / len(inference_times)
                                  if inference_times else None),
            average_processing_ms=sum(ms for _, _, _, ms in events) / len(events),
        )
