"""Camera capture and angle-telemetry adapters."""

from .runtime import (
    AngleReading,
    CameraMode,
    FixedUSBCamera,
    FrameRateMeter,
    RuntimeIOError,
    TelemetryAngleSource,
    interpolate_angle_samples,
)

__all__ = [
    "AngleReading",
    "CameraMode",
    "FixedUSBCamera",
    "FrameRateMeter",
    "RuntimeIOError",
    "TelemetryAngleSource",
    "interpolate_angle_samples",
]
