"""Calibration, state estimation, and tracking domain logic."""

from .calibration import (
    AngleCalibrationSample,
    DynamicCalibration,
    DynamicCalibrationError,
    RectificationState,
    compute_homography,
    destination_corners,
    fit_position_polynomial,
    order_quad_points,
)
from .estimator import ConstantVelocityKalman
from .tracker import (
    DynamicBallTracker,
    DynamicTrackerConfig,
    DynamicTrackingResult,
    draw_tracking_overlay,
)

__all__ = [
    "AngleCalibrationSample",
    "ConstantVelocityKalman",
    "DynamicBallTracker",
    "DynamicCalibration",
    "DynamicCalibrationError",
    "DynamicTrackerConfig",
    "DynamicTrackingResult",
    "RectificationState",
    "compute_homography",
    "destination_corners",
    "draw_tracking_overlay",
    "fit_position_polynomial",
    "order_quad_points",
]
