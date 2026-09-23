"""Common camera/tracker loop with pluggable angle sources and UI policy."""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import time
from typing import Callable

import cv2
import numpy as np

from .tracking_setup import TrackingComponents
from .tracking_support import format_result
from ..core.calibration import DynamicCalibrationError
from ..core.tracker import DynamicTrackingResult, draw_tracking_overlay
from ..io.runtime import FrameRateMeter


@dataclass(frozen=True, slots=True)
class FrameAngle:
    angle_deg: float | None
    invalid_reason: str = "angle-missing"
    rectification_reason: str = "rectification-invalid"
    report_prefix: str = ""


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


class VisionRateStats:
    """Rolling one-second rates for loop output and model-backed detections."""

    def __init__(self, window_seconds: float = 1.0) -> None:
        self.window_seconds = float(window_seconds)
        self._events: deque[tuple[float, bool, float, float]] = deque()

    def update(self, now: float, result: DynamicTrackingResult) -> None:
        detected = (
            result.measurement_valid
            and result.source in {"yolo_box", "ransac"}
            and result.inference_ms > 0.0
        )
        self._events.append(
            (
                now,
                detected,
                float(result.inference_ms),
                float(result.processing_ms),
            )
        )
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def format(self) -> str:
        if len(self._events) < 2:
            return (
                "rates=warming detect_hz=warming track_hz=warming "
                "avg_infer=warming avg_total=warming"
            )
        elapsed = max(1e-6, self._events[-1][0] - self._events[0][0])
        loop_hz = len(self._events) / elapsed
        detect_count = sum(1 for _, detected, _, _ in self._events if detected)
        detect_hz = detect_count / elapsed
        track_hz = max(0.0, loop_hz - detect_hz)
        infer_values = [
            infer_ms
            for _, detected, infer_ms, _ in self._events
            if detected and infer_ms > 0.0
        ]
        total_values = [total_ms for _, _, _, total_ms in self._events]
        avg_infer = (
            sum(infer_values) / len(infer_values)
            if infer_values
            else 0.0
        )
        avg_total = sum(total_values) / len(total_values)
        return (
            f"loop_hz={loop_hz:.1f} detect_hz={detect_hz:.1f} "
            f"track_hz={track_hz:.1f} avg_infer={avg_infer:.2f}ms "
            f"avg_total={avg_total:.2f}ms"
        )


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
    next_report = started
    fps_meter = FrameRateMeter(window_seconds=1.0)
    rate_stats = VisionRateStats(window_seconds=1.0)
    last_display_canvas: np.ndarray | None = None

    camera.open()
    try:
        camera.warm_up(args.warmup_frames)
        while finish_at is None or time.perf_counter() < finish_at:
            if before_capture is not None:
                before_capture()
            frame, timestamp = camera.read()
            decision = angle_for_frame(timestamp)

            if decision.angle_deg is None:
                result = tracker.process_missing_angle(
                    timestamp,
                    decision.invalid_reason,
                )
            else:
                try:
                    result = tracker.process(
                        frame,
                        decision.angle_deg,
                        timestamp,
                    )
                except DynamicCalibrationError as exc:
                    result = tracker.process_missing_angle(
                        timestamp,
                        f"{decision.rectification_reason}:{exc}",
                    )

            if result_handler is not None:
                result_handler(result)
            if frame_handler is not None:
                frame_handler(frame)

            now = time.perf_counter()
            fps = fps_meter.update(now)
            rate_stats.update(now, result)
            if now >= next_report:
                print(
                    decision.report_prefix
                    + format_result(result, fps=fps)
                    + " "
                    + rate_stats.format(),
                    flush=True,
                )
                next_report = now + args.report_period

            if not args.no_display:
                canvas = draw_tracking_overlay(result, fps=fps)
                if canvas is None:
                    fallback_frame = (
                        last_display_canvas.copy()
                        if hold_last_display_on_missing
                        and last_display_canvas is not None
                        else frame
                    )
                    canvas = (
                        fallback_frame
                        if fallback_overlay is None
                        else fallback_overlay(fallback_frame, result, fps)
                    )
                else:
                    last_display_canvas = canvas.copy()
                if decorate_overlay is not None:
                    canvas = decorate_overlay(canvas, decision, fps)
                cv2.imshow(window_name, canvas)
                key = cv2.waitKeyEx(1)
                if key in (ord("q"), ord("Q"), 27):
                    break
                if key_handler is not None:
                    key_handler(key)
        return 0
    finally:
        camera.close()
        cv2.destroyAllWindows()
