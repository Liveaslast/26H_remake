"""Stable result types for the adaptive detector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Point = tuple[float, float]
Box = tuple[float, float, float, float]
DetectionSource = Literal["ransac", "yolo_box", "cached_ransac", "tracked"]
FrameSource = Literal["detected", "tracked"]


@dataclass(frozen=True, slots=True)
class CircleRefinement:
    success: bool
    center_px: Point
    radius_px: float
    arc_coverage: float
    mean_residual_px: float | None
    inlier_count: int
    candidate_count: int
    reason: str


@dataclass(frozen=True, slots=True)
class StageTimings:
    """Per-frame timing breakdown in milliseconds.

    The Ultralytics path reports ``model_call_ms`` because its Python wrapper
    owns preprocessing and postprocessing internally. The native NCNN path
    fills the finer-grained model timings as well.
    """

    total_ms: float = 0.0
    model_load_ms: float = 0.0
    model_call_ms: float = 0.0
    preprocess_ms: float = 0.0
    inference_ms: float = 0.0
    postprocess_ms: float = 0.0
    association_ms: float = 0.0
    refinement_ms: float = 0.0
    cache_update_ms: float = 0.0
    tracking_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class BallDetection:
    box_xyxy: Box
    confidence: float
    class_id: int
    center_px: Point
    radius_px: float
    source: DetectionSource
    arc_coverage: float | None = None
    mean_residual_px: float | None = None
    inlier_count: int = 0

    @property
    def diameter_px(self) -> float:
        return self.radius_px * 2.0


@dataclass(frozen=True, slots=True)
class AdaptiveFrameDetection:
    balls: tuple[BallDetection, ...]
    inference_ms: float
    refinement_ms: float
    refined_count: int
    reused_count: int
    frame_index: int
    associated_count: int = 0
    unmatched_count: int = 0
    ambiguous_count: int = 0
    motion_refined_count: int = 0
    periodic_refined_count: int = 0
    ransac_success_count: int = 0
    ransac_failure_count: int = 0
    mode: str = "balanced"
    frame_source: FrameSource = "detected"
    tracking_ms: float = 0.0
    valid_track_points: int = 0
    tracking_quality: float = 1.0
    correction_requested: bool = False
    correction_reason: str | None = None
    timings: StageTimings = field(default_factory=StageTimings)

    @property
    def count(self) -> int:
        return len(self.balls)
