"""Extract ball measurements without smoothing, deadbands or jump suppression."""

from dataclasses import dataclass
import math

from .tracker import DynamicTrackingResult


@dataclass(frozen=True)
class BallState:
    """Final control input: cm, cm/s, validity and Pi image-read monotonic time."""
    position_cm: float
    velocity_cm_s: float
    valid: bool
    measured_at: float
"""
球状态获取器:
    获取小球位置、速度、有效性、图像时间
"""

def measurement_state(result: DynamicTrackingResult) -> BallState:
    """Explicit current policy: measurement position (fallback: tracker position), tracker velocity.

    Raw measurements remain on result for diagnostics. No extra filter is applied here.
    """
    position = result.measurement_position_cm
    if position is None:
        position = result.position_cm
    velocity = result.velocity_cm_s
    valid = bool(
        result.measurement_valid and result.tracking_valid
        and position is not None and velocity is not None
        and math.isfinite(position) and math.isfinite(velocity)
    )
    return BallState(float(position) if valid else 0.0, float(velocity) if valid else 0.0,
                     valid, float(result.timestamp))


class BallStateBuilder:
    """Build final control input from one source; never reselect raw fields afterwards."""

    def __init__(self, state_source=measurement_state):
        self.state_source = state_source
        self._position_cm = 0.0
        self._velocity_cm_s = 0.0

    def update(self, result: DynamicTrackingResult) -> BallState:
        state = self.state_source(result)
        valid = bool(state.valid and math.isfinite(state.position_cm)
                     and math.isfinite(state.velocity_cm_s))
        if valid:
            self._position_cm = float(state.position_cm)
            self._velocity_cm_s = float(state.velocity_cm_s)
        return BallState(self._position_cm, self._velocity_cm_s, valid, state.measured_at)
