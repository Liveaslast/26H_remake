"""YOLO detector that amortizes expensive circle refinement across frames."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import time
from typing import Any, Callable, Literal

import numpy as np
import cv2

from ..detection_common.circle_refine import CircleRefineConfig, refine_circle

from .models import AdaptiveFrameDetection, BallDetection, Box, CircleRefinement, StageTimings


CircleRefiner = Callable[[np.ndarray, Box, CircleRefineConfig], CircleRefinement]
AdaptiveMode = Literal["performance", "balanced", "precision"]


@dataclass(frozen=True, slots=True)
class AdaptiveBallDetectorConfig:
    model_path: str | Path = "models/balls_ncnn_model"
    image_size: int | tuple[int, int] = 512
    confidence: float = 0.35
    iou_threshold: float = 0.70
    class_id: int = 0
    max_detections: int = 300
    mode: AdaptiveMode = "balanced"
    refine_interval: int = 8
    association_iou: float = 0.0
    association_center_distance_ratio: float = 1.25
    association_scale_change_ratio: float = 0.55
    association_ambiguity_margin: float = 0.10
    max_center_shift_ratio: float = 0.50
    max_scale_change_ratio: float = 0.45
    cache_max_missed_frames: int = 3
    detection_interval: int = 2
    track_max_corners: int = 30
    track_min_points: int = 5
    track_quality_level: float = 0.01
    track_min_distance: float = 3.0
    track_fb_error: float = 1.5
    track_max_dispersion: float = 4.0
    track_max_shift_ratio: float = 0.75
    track_scale: float = 0.5
    ncnn_backend: Literal["ultralytics", "cpp", "hailo", "hailort"] = "ultralytics"
    ncnn_threads: int = 2
    circle_backend: Literal["python", "cpp"] = "python"
    circle: CircleRefineConfig = field(default_factory=lambda: CircleRefineConfig(ransac_iterations=150))

    def __post_init__(self) -> None:
        raw_size = self.image_size
        if isinstance(raw_size, bool):
            raise ValueError("image_size must be an integer or (height, width)")
        if isinstance(raw_size, int):
            normalized_size: int | tuple[int, int] = int(raw_size)
            dimensions = (normalized_size,)
        elif isinstance(raw_size, (tuple, list)) and len(raw_size) == 2:
            normalized_size = (int(raw_size[0]), int(raw_size[1]))
            dimensions = normalized_size
        else:
            raise ValueError("image_size must be an integer or (height, width)")
        if any(dimension <= 0 for dimension in dimensions) or self.max_detections <= 0:
            raise ValueError("image_size and max_detections must be positive")
        object.__setattr__(self, "image_size", normalized_size)
        if not 0 <= self.confidence <= 1 or not 0 <= self.iou_threshold <= 1:
            raise ValueError("confidence and iou_threshold must be within [0, 1]")
        if self.mode not in ("performance", "balanced", "precision"):
            raise ValueError("mode must be performance, balanced, or precision")
        if self.ncnn_backend not in ("ultralytics", "cpp", "hailo", "hailort"):
            raise ValueError("ncnn_backend must be ultralytics, cpp, hailo, or hailort")
        if self.ncnn_threads <= 0:
            raise ValueError("ncnn_threads must be positive")
        if self.circle_backend not in ("python", "cpp"):
            raise ValueError("circle_backend must be python or cpp")
        if not 0 <= self.association_iou <= 1:
            raise ValueError("association_iou must be within [0, 1]")
        if self.refine_interval <= 0 or self.detection_interval <= 0 or self.cache_max_missed_frames < 0:
            raise ValueError("refine_interval must be positive and cache lifetime non-negative")
        if self.track_max_corners <= 0 or self.track_min_points <= 0 or self.track_min_points > self.track_max_corners:
            raise ValueError("invalid optical-flow point limits")
        if min(self.track_quality_level, self.track_min_distance, self.track_fb_error,
               self.track_max_dispersion, self.track_max_shift_ratio, self.track_scale) <= 0:
            raise ValueError("optical-flow thresholds must be positive")
        if self.track_scale > 1:
            raise ValueError("track_scale must be within (0, 1]")
        if min(self.max_center_shift_ratio, self.max_scale_change_ratio, self.association_center_distance_ratio,
               self.association_scale_change_ratio, self.association_ambiguity_margin) < 0:
            raise ValueError("association and movement thresholds must be non-negative")


def detector_config_for_mode(mode: AdaptiveMode, **overrides: Any) -> AdaptiveBallDetectorConfig:
    """Return a complete preset; explicit keyword overrides always win."""
    presets: dict[AdaptiveMode, dict[str, Any]] = {
        "performance": dict(refine_interval=15, association_center_distance_ratio=1.75,
                            association_scale_change_ratio=0.75, association_ambiguity_margin=0.10,
                            max_center_shift_ratio=0.85, max_scale_change_ratio=0.70,
                            cache_max_missed_frames=4, circle=CircleRefineConfig(ransac_iterations=75)),
        "balanced": dict(refine_interval=8, association_center_distance_ratio=1.25,
                         association_scale_change_ratio=0.55, association_ambiguity_margin=0.10,
                         max_center_shift_ratio=0.50, max_scale_change_ratio=0.45,
                         cache_max_missed_frames=3, circle=CircleRefineConfig(ransac_iterations=150)),
        "precision": dict(refine_interval=3, association_center_distance_ratio=0.90,
                          association_scale_change_ratio=0.40, association_ambiguity_margin=0.08,
                          max_center_shift_ratio=0.30, max_scale_change_ratio=0.30,
                          cache_max_missed_frames=2,
                          circle=CircleRefineConfig(
                              ransac_iterations=150,
                              max_center_offset_ratio=0.15,
                          )),
    }
    return AdaptiveBallDetectorConfig(mode=mode, **(presets[mode] | overrides))


@dataclass(slots=True)
class _CachedBall:
    box: Box
    previous_box: Box
    center_velocity: tuple[float, float]
    circle: CircleRefinement
    last_refined_frame: int
    missed_frames: int = 0
    association_cost: float = 0.0


@dataclass(slots=True)
class _FlowTrack:
    ball: BallDetection
    points: np.ndarray


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def _box_center(box: Box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _box_scale(box: Box) -> float:
    return max(1e-6, ((box[2] - box[0]) + (box[3] - box[1])) / 2.0)


def _refinement_matches_box(
    refinement: CircleRefinement,
    box: Box,
    max_offset_ratio: float,
) -> bool:
    """Reject a fitted center that is implausibly far from its YOLO box.

    The rectified rod image is anisotropically scaled, so the steel ball is
    generally elliptical rather than circular. Normalize center error by the
    box width and height independently; using only the longest side lets a
    tall box tolerate an excessive horizontal error, which directly corrupts
    the one-dimensional ball position.
    """

    if not refinement.success:
        return False
    width = float(box[2] - box[0])
    height = float(box[3] - box[1])
    center_x, center_y = map(float, refinement.center_px)
    radius = float(refinement.radius_px)
    if (
        width <= 0.0
        or height <= 0.0
        or radius <= 0.0
        or not all(
            np.isfinite(value)
            for value in (center_x, center_y, radius, max_offset_ratio)
        )
        or max_offset_ratio < 0.0
    ):
        return False
    box_center_x, box_center_y = _box_center(box)
    if max_offset_ratio == 0.0:
        return (
            abs(center_x - box_center_x) <= 1e-6
            and abs(center_y - box_center_y) <= 1e-6
        )
    normalized_x = (center_x - box_center_x) / (
        max_offset_ratio * width
    )
    normalized_y = (center_y - box_center_y) / (
        max_offset_ratio * height
    )
    return float(np.hypot(normalized_x, normalized_y)) <= 1.0


def _box_center_detection(
    box: Box,
    confidence: float,
    class_id: int,
) -> BallDetection:
    return BallDetection(
        box,
        confidence,
        class_id,
        _box_center(box),
        _box_scale(box) / 2.0,
        "yolo_box",
    )


def _translate_box(box: Box, shift: tuple[float, float]) -> Box:
    return (box[0] + shift[0], box[1] + shift[1], box[2] + shift[0], box[3] + shift[1])


def _iou(first: Box, second: Box) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection <= 0:
        return 0.0
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    return intersection / max(1e-6, first_area + second_area - intersection)


class AdaptiveBallDetector:
    def __init__(self, config: AdaptiveBallDetectorConfig | None = None, *, model: Any | None = None,
                 circle_refiner: CircleRefiner = refine_circle) -> None:
        self.config = config or AdaptiveBallDetectorConfig()
        self._model = model
        self._circle_refiner = circle_refiner
        if self.config.circle_backend == "cpp" and circle_refiner is refine_circle:
            from .circle_refine_native import refine_circle_native

            self._circle_refiner = refine_circle_native
        self._cache: list[_CachedBall] = []
        self._frame_index = 0
        self._previous_gray: np.ndarray | None = None
        self._flow_tracks: list[_FlowTrack] = []
        self._force_detection = True
        self._model_load_ms = 0.0

    def reset_tracking(self) -> None:
        """Clear temporal state while retaining the already loaded model."""

        self._cache.clear()
        self._frame_index = 0
        self._previous_gray = None
        self._flow_tracks.clear()
        self._force_detection = True

    def _features(self, gray: np.ndarray, box: Box) -> np.ndarray:
        height, width = gray.shape
        x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
        x2, y2 = min(width, int(np.ceil(box[2]))), min(height, int(np.ceil(box[3])))
        mask = np.zeros_like(gray)
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255
        points = cv2.goodFeaturesToTrack(gray, mask=mask, maxCorners=self.config.track_max_corners,
                                         qualityLevel=self.config.track_quality_level,
                                         minDistance=self.config.track_min_distance)
        return np.empty((0, 1, 2), np.float32) if points is None else points.astype(np.float32)

    def _flow_gray(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.config.track_scale == 1:
            return gray
        return cv2.resize(gray, None, fx=self.config.track_scale, fy=self.config.track_scale,
                          interpolation=cv2.INTER_AREA)

    def _flow_box(self, box: Box) -> Box:
        scale = self.config.track_scale
        return tuple(value * scale for value in box)  # type: ignore[return-value]

    def _initialize_flow(self, frame: np.ndarray, balls: tuple[BallDetection, ...]) -> None:
        gray = self._flow_gray(frame)
        self._previous_gray = gray
        self._flow_tracks = [_FlowTrack(ball, self._features(gray, self._flow_box(ball.box_xyxy))) for ball in balls]

    @staticmethod
    def _boxes_overlap(first: Box, second: Box) -> bool:
        return _iou(first, second) > 0.35

    def _track(self, frame: np.ndarray) -> AdaptiveFrameDetection:
        started = time.perf_counter()
        gray = self._flow_gray(frame)
        balls: list[BallDetection] = []
        next_tracks: list[_FlowTrack] = []
        valid_total = 0
        qualities: list[float] = []
        reason: str | None = None
        if self._previous_gray is None or not self._flow_tracks:
            reason = "not_initialized"
        else:
            eligible: list[tuple[_FlowTrack, int, int]] = []
            point_groups: list[np.ndarray] = []
            offset = 0
            for track in self._flow_tracks:
                count = len(track.points)
                if count < self.config.track_min_points:
                    reason = reason or "too_few_points"
                    continue
                point_groups.append(track.points)
                eligible.append((track, offset, offset + count))
                offset += count
            all_points = np.concatenate(point_groups, axis=0) if point_groups else None
            forward = status = backward = back_status = None
            if all_points is not None:
                forward, status, _ = cv2.calcOpticalFlowPyrLK(self._previous_gray, gray, all_points, None)
                if forward is None or status is None:
                    reason = reason or "flow_failed"
                else:
                    backward, back_status, _ = cv2.calcOpticalFlowPyrLK(gray, self._previous_gray, forward, None)
                    if backward is None or back_status is None:
                        reason = reason or "backward_flow_failed"
            for track, begin, end in eligible:
                if forward is None or status is None or backward is None or back_status is None or all_points is None:
                    continue
                original = all_points[begin:end].reshape(-1, 2)
                returned = backward[begin:end].reshape(-1, 2)
                fb = np.linalg.norm(original - returned, axis=1)
                keep = ((status[begin:end].reshape(-1) == 1) & (back_status[begin:end].reshape(-1) == 1)
                        & (fb <= self.config.track_fb_error * self.config.track_scale))
                old = original[keep]
                new = forward[begin:end].reshape(-1, 2)[keep]
                if len(new) < self.config.track_min_points:
                    reason = reason or "too_few_points"
                    continue
                shifts = new - old
                flow_shift = np.median(shifts, axis=0)
                flow_dispersion = float(np.median(np.linalg.norm(shifts - flow_shift, axis=1)))
                shift = flow_shift / self.config.track_scale
                dispersion = flow_dispersion / self.config.track_scale
                if dispersion > self.config.track_max_dispersion:
                    reason = reason or "inconsistent_motion"
                    continue
                box = _translate_box(track.ball.box_xyxy, (float(shift[0]), float(shift[1])))
                height, width = frame.shape[:2]
                scale = _box_scale(track.ball.box_xyxy)
                if float(np.linalg.norm(shift)) > scale * self.config.track_max_shift_ratio:
                    reason = reason or "excessive_shift"
                    continue
                if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
                    reason = reason or "out_of_bounds"
                    continue
                center = (track.ball.center_px[0] + float(shift[0]), track.ball.center_px[1] + float(shift[1]))
                ball = replace(track.ball, box_xyxy=box, center_px=center, source="tracked")
                retained = new.reshape(-1, 1, 2).astype(np.float32)
                quality = float(len(new) / max(1, len(track.points)))
                valid_total += len(new)
                qualities.append(quality)
                balls.append(ball)
                next_tracks.append(_FlowTrack(ball, retained))
            if any(self._boxes_overlap(balls[i].box_xyxy, balls[j].box_xyxy)
                   for i in range(len(balls)) for j in range(i + 1, len(balls))):
                reason = reason or "overlap"
        self._previous_gray = gray
        self._flow_tracks = next_tracks
        self._force_detection = reason is not None
        tracking_ms = (time.perf_counter() - started) * 1000.0
        return AdaptiveFrameDetection(tuple(balls), 0.0, 0.0, 0, 0, self._frame_index,
                                      mode=self.config.mode, frame_source="tracked", tracking_ms=tracking_ms,
                                      valid_track_points=valid_total,
                                      tracking_quality=min(qualities) if qualities else 0.0,
                                      correction_requested=self._force_detection, correction_reason=reason,
                                      timings=StageTimings(total_ms=tracking_ms, tracking_ms=tracking_ms))

    def _get_model(self) -> Any:
        if self._model is None:
            started = time.perf_counter()
            if self.config.ncnn_backend == "cpp":
                from .ncnn_backend import CppNcnnBackend

                self._model = CppNcnnBackend(self.config.model_path, threads=self.config.ncnn_threads)
                self._model_load_ms = (time.perf_counter() - started) * 1000.0
                return self._model
            if self.config.ncnn_backend == "hailo":
                from .hailo_backend import HailoUltralyticsBackend

                self._model = HailoUltralyticsBackend(self.config.model_path)
                self._model_load_ms = (time.perf_counter() - started) * 1000.0
                return self._model
            if self.config.ncnn_backend == "hailort":
                from .hailort_backend import NativeHailoRtBackend

                self._model = NativeHailoRtBackend(self.config.model_path)
                self._model_load_ms = (time.perf_counter() - started) * 1000.0
                return self._model
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError("Install ultralytics and ncnn before running this detector") from exc
            self._model = YOLO(str(self.config.model_path), task="detect")
            self._model_load_ms = (time.perf_counter() - started) * 1000.0
        return self._model

    def _predicted_box(self, cached: _CachedBall) -> Box:
        multiplier = max(1, cached.missed_frames + 1)
        return _translate_box(cached.box, (cached.center_velocity[0] * multiplier, cached.center_velocity[1] * multiplier))

    def _association_cost(self, box: Box, cached: _CachedBall) -> float | None:
        predicted = self._predicted_box(cached)
        predicted_center, current_center = _box_center(predicted), _box_center(box)
        center_distance = float(np.hypot(current_center[0] - predicted_center[0], current_center[1] - predicted_center[1]))
        center_ratio = center_distance / _box_scale(predicted)
        scale_ratio = abs(_box_scale(box) / _box_scale(predicted) - 1.0)
        overlap = _iou(box, predicted)
        if (center_ratio > self.config.association_center_distance_ratio
                or scale_ratio > self.config.association_scale_change_ratio
                or overlap < self.config.association_iou):
            return None
        return (0.65 * center_ratio / max(self.config.association_center_distance_ratio, 1e-6)
                + 0.25 * scale_ratio / max(self.config.association_scale_change_ratio, 1e-6)
                + 0.10 * (1.0 - overlap))

    def _associate(self, boxes: list[Box]) -> tuple[dict[int, tuple[int, float]], set[int], int]:
        """Globally match detections to predicted tracks and reject ambiguous pairs."""
        candidates: list[tuple[float, int, int]] = []
        per_box: dict[int, list[float]] = {index: [] for index in range(len(boxes))}
        per_cache: dict[int, list[float]] = {index: [] for index in range(len(self._cache))}
        for box_index, box in enumerate(boxes):
            for cache_index, cached in enumerate(self._cache):
                cost = self._association_cost(box, cached)
                if cost is not None:
                    candidates.append((cost, box_index, cache_index))
                    per_box[box_index].append(cost)
                    per_cache[cache_index].append(cost)
        ambiguous_boxes: set[int] = set()
        ambiguous_caches: set[int] = set()
        margin = self.config.association_ambiguity_margin
        for index, costs in per_box.items():
            if len(costs) > 1 and sorted(costs)[1] - sorted(costs)[0] <= margin:
                ambiguous_boxes.add(index)
        for index, costs in per_cache.items():
            if len(costs) > 1 and sorted(costs)[1] - sorted(costs)[0] <= margin:
                ambiguous_caches.add(index)
        matches: dict[int, tuple[int, float]] = {}
        used_boxes: set[int] = set()
        used_caches: set[int] = set()
        for cost, box_index, cache_index in sorted(candidates):
            if (box_index in used_boxes or cache_index in used_caches or box_index in ambiguous_boxes
                    or cache_index in ambiguous_caches):
                continue
            matches[box_index] = (cache_index, cost)
            used_boxes.add(box_index)
            used_caches.add(cache_index)
        return matches, ambiguous_boxes, len(candidates)

    def _is_motion_large(self, previous: Box, current: Box) -> bool:
        old_center, new_center = _box_center(previous), _box_center(current)
        shift = float(np.hypot(new_center[0] - old_center[0], new_center[1] - old_center[1]))
        scale = _box_scale(previous)
        relative_scale_change = abs(_box_scale(current) / scale - 1.0)
        return shift / scale > self.config.max_center_shift_ratio or relative_scale_change > self.config.max_scale_change_ratio

    @staticmethod
    def _transform_circle(circle: CircleRefinement, previous: Box, current: Box) -> CircleRefinement:
        old_center, new_center = _box_center(previous), _box_center(current)
        scale = _box_scale(current) / _box_scale(previous)
        return CircleRefinement(True, (new_center[0] + (circle.center_px[0] - old_center[0]) * scale,
                                       new_center[1] + (circle.center_px[1] - old_center[1]) * scale),
                                circle.radius_px * scale, circle.arc_coverage, circle.mean_residual_px,
                                circle.inlier_count, circle.candidate_count, "cached refinement")

    def detect(self, frame: np.ndarray) -> AdaptiveFrameDetection:
        if not isinstance(frame, np.ndarray) or frame.size == 0:
            raise ValueError("frame must be a non-empty numpy.ndarray")
        started = time.perf_counter()
        self._frame_index += 1
        detection_frame = (self._force_detection or self.config.detection_interval == 1
                           or (self._frame_index - 1) % self.config.detection_interval == 0)
        if not detection_frame:
            return self._track(frame)
        self._force_detection = False
        result = self._detect_yolo(frame)
        self._initialize_flow(frame, result.balls)
        return replace(result, timings=replace(result.timings,
                                               total_ms=(time.perf_counter() - started) * 1000.0))

    def _detect_yolo(self, frame: np.ndarray) -> AdaptiveFrameDetection:
        started = time.perf_counter()
        model = self._get_model()
        prediction = model.predict(source=frame, imgsz=self.config.image_size, conf=self.config.confidence,
                                   iou=self.config.iou_threshold, classes=[self.config.class_id],
                                   max_det=self.config.max_detections, verbose=False)[0]
        model_call_ms = (time.perf_counter() - started) * 1000.0
        backend_timings = getattr(prediction, "timings", None)
        model_load_ms = self._model_load_ms
        self._model_load_ms = 0.0
        if backend_timings is None:
            # Ultralytics does not expose its internal split; keep the full
            # wrapper call visible in the inference bucket instead of hiding it.
            model_preprocess_ms = model_postprocess_ms = 0.0
            model_inference_ms = model_call_ms
            inference_ms = model_call_ms
        else:
            model_preprocess_ms = float(getattr(backend_timings, "preprocess_ms", 0.0))
            model_inference_ms = float(getattr(backend_timings, "inference_ms", model_call_ms))
            model_postprocess_ms = float(getattr(backend_timings, "postprocess_ms", 0.0))
            inference_ms = model_inference_ms
        boxes_object = getattr(prediction, "boxes", None)
        if boxes_object is None or len(boxes_object) == 0:
            self._cache = [item for item in self._cache if item.missed_frames + 1 <= self.config.cache_max_missed_frames]
            for item in self._cache:
                item.missed_frames += 1
            return AdaptiveFrameDetection(
                (), inference_ms, 0.0, 0, 0, self._frame_index, mode=self.config.mode,
                timings=StageTimings(model_load_ms=model_load_ms, model_call_ms=model_call_ms,
                                     preprocess_ms=model_preprocess_ms, inference_ms=model_inference_ms,
                                     postprocess_ms=model_postprocess_ms),
            )
        boxes, confidences, classes = (_to_numpy(boxes_object.xyxy).reshape(-1, 4), _to_numpy(boxes_object.conf).reshape(-1), _to_numpy(boxes_object.cls).reshape(-1))
        valid: list[tuple[Box, float, int]] = []
        for index in range(min(len(boxes), len(confidences), len(classes))):
            class_id, confidence = int(round(float(classes[index]))), float(confidences[index])
            x1, y1, x2, y2 = (float(value) for value in boxes[index])
            if class_id == self.config.class_id and confidence >= self.config.confidence and x2 > x1 and y2 > y1:
                valid.append(((x1, y1, x2, y2), confidence, class_id))
        association_started = time.perf_counter()
        matches, ambiguous_boxes, candidate_count = self._associate([item[0] for item in valid])
        association_ms = (time.perf_counter() - association_started) * 1000.0
        used_cache = {cache_index for cache_index, _ in matches.values()}
        next_cache: list[_CachedBall] = []
        balls: list[BallDetection] = []
        refined_count = reused_count = motion_refined = periodic_refined = successes = failures = 0
        refine_started = time.perf_counter()
        for index, (box, confidence, class_id) in enumerate(valid):
            match = matches.get(index)
            force_refine = match is None or index in ambiguous_boxes
            cached: _CachedBall | None = None
            reason = "unmatched" if match is None else "ambiguous"
            if match is not None:
                cache_index, _ = match
                cached = self._cache[cache_index]
                if self._is_motion_large(cached.box, box):
                    force_refine, reason = True, "motion"
                elif self._frame_index - cached.last_refined_frame >= self.config.refine_interval:
                    force_refine, reason = True, "periodic"
            if force_refine:
                refinement = self._circle_refiner(frame, box, self.config.circle)
                refined_count += 1
                motion_refined += reason == "motion"
                periodic_refined += reason == "periodic"
                if _refinement_matches_box(
                    refinement,
                    box,
                    self.config.circle.max_center_offset_ratio,
                ):
                    old_center = _box_center(cached.box) if cached else _box_center(box)
                    new_center = _box_center(box)
                    velocity = (new_center[0] - old_center[0], new_center[1] - old_center[1]) if cached else (0.0, 0.0)
                    next_cache.append(_CachedBall(box, cached.box if cached else box, velocity, refinement, self._frame_index,
                                                  association_cost=match[1] if match else 1.0))
                    successes += 1
                    balls.append(BallDetection(box, confidence, class_id, refinement.center_px, refinement.radius_px, "ransac", refinement.arc_coverage, refinement.mean_residual_px, refinement.inlier_count))
                    continue
                failures += 1
                if cached is None:
                    balls.append(
                        _box_center_detection(box, confidence, class_id)
                    )
                    continue
            assert cached is not None
            assert match is not None
            refinement = self._transform_circle(cached.circle, cached.box, box)
            if not _refinement_matches_box(
                refinement,
                box,
                self.config.circle.max_center_offset_ratio,
            ):
                failures += 1
                balls.append(_box_center_detection(box, confidence, class_id))
                continue
            previous_center, current_center = _box_center(cached.box), _box_center(box)
            velocity = (current_center[0] - previous_center[0], current_center[1] - previous_center[1])
            next_cache.append(_CachedBall(box, cached.box, velocity, refinement, cached.last_refined_frame,
                                          association_cost=match[1]))
            reused_count += 1
            balls.append(BallDetection(box, confidence, class_id, refinement.center_px, refinement.radius_px, "cached_ransac", refinement.arc_coverage, refinement.mean_residual_px, refinement.inlier_count))
        cache_update_started = time.perf_counter()
        for cache_index, cached in enumerate(self._cache):
            if cache_index not in used_cache and cached.missed_frames + 1 <= self.config.cache_max_missed_frames:
                cached.missed_frames += 1
                next_cache.append(cached)
        self._cache = next_cache
        cache_update_ms = (time.perf_counter() - cache_update_started) * 1000.0
        refinement_ms = (time.perf_counter() - refine_started) * 1000.0
        balls.sort(key=lambda item: item.confidence, reverse=True)
        return AdaptiveFrameDetection(tuple(balls), inference_ms, refinement_ms, refined_count, reused_count, self._frame_index,
                                      associated_count=len(matches), unmatched_count=len(valid) - len(matches),
                                      ambiguous_count=len(ambiguous_boxes), motion_refined_count=motion_refined,
                                      periodic_refined_count=periodic_refined, ransac_success_count=successes,
                                      ransac_failure_count=failures, mode=self.config.mode,
                                      timings=StageTimings(model_load_ms=model_load_ms, model_call_ms=model_call_ms,
                                                           preprocess_ms=model_preprocess_ms,
                                                           inference_ms=model_inference_ms,
                                                           postprocess_ms=model_postprocess_ms,
                                                           association_ms=association_ms,
                                                           refinement_ms=refinement_ms,
                                                           cache_update_ms=cache_update_ms))
