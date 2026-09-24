"""Adaptive, frame-rate-oriented YOLO steel-ball detection."""

from .detector import AdaptiveBallDetector, AdaptiveBallDetectorConfig, detector_config_for_mode
from .models import AdaptiveFrameDetection, BallDetection, CircleRefinement, StageTimings

__all__ = [
    "AdaptiveBallDetector",
    "AdaptiveBallDetectorConfig",
    "AdaptiveFrameDetection",
    "BallDetection",
    "CircleRefinement",
    "StageTimings",
    "detector_config_for_mode",
]
