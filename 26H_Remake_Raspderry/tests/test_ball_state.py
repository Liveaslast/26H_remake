"""Measurements pass through unchanged; invalid samples remain marked invalid."""

from types import SimpleNamespace
import unittest

from ballbeam.vision.ball_state import BallState, BallStateBuilder, measurement_state


def result(**updates):
    fields = dict(timestamp=1.0, measurement_position_cm=2.5, position_cm=2.0,
                  velocity_cm_s=3.0, measurement_valid=True, tracking_valid=True)
    fields.update(updates)
    return SimpleNamespace(**fields)


class BallStateTests(unittest.TestCase):
    def test_measurement_and_timestamp_pass_through(self):
        self.assertEqual(BallStateBuilder().update(result()), BallState(2.5, 3, True, 1))

    def test_invalid_measurement_keeps_last_values_but_marks_invalid(self):
        builder = BallStateBuilder()
        builder.update(result())
        self.assertEqual(builder.update(result(timestamp=2, measurement_valid=False)),
                         BallState(2.5, 3, False, 2))

    def test_first_invalid_measurement_is_invalid_zero_state(self):
        self.assertEqual(BallStateBuilder().update(result(measurement_valid=False)),
                         BallState(0, 0, False, 1))

    def test_nonfinite_or_missing_values_are_invalid(self):
        for updates in (dict(velocity_cm_s=float("nan")),
                        dict(measurement_position_cm=float("inf")),
                        dict(velocity_cm_s=None), dict(tracking_valid=False)):
            with self.subTest(updates=updates):
                self.assertFalse(BallStateBuilder().update(result(**updates)).valid)

    def test_jumps_zero_crossings_and_small_velocities_are_not_suppressed(self):
        builder = BallStateBuilder()
        for timestamp, position, velocity in ((1, -10, -5), (2, 10, 5),
                                               (3, 0, .001), (4, .0001, -.0001)):
            state = builder.update(result(timestamp=timestamp,
                measurement_position_cm=position, velocity_cm_s=velocity))
            self.assertEqual(state, BallState(position, velocity, True, timestamp))

    def test_position_fallback_is_preserved(self):
        state = BallStateBuilder().update(result(measurement_position_cm=None))
        self.assertEqual(state.position_cm, 2.0)

    def test_default_source_policy_is_explicit_and_does_not_modify_raw_result(self):
        raw = result()
        self.assertEqual(measurement_state(raw), BallState(2.5, 3, True, 1))
        self.assertEqual(raw.measurement_position_cm, 2.5)
        self.assertEqual(raw.position_cm, 2)

    def test_selected_final_state_is_not_overwritten_with_raw_fields(self):
        raw = result()
        final_state = BallState(.25, -.75, True, raw.timestamp)
        builder = BallStateBuilder(state_source=lambda _: final_state)
        self.assertEqual(builder.update(raw), final_state)
        self.assertEqual(raw.measurement_position_cm, 2.5)

    def test_invalid_selected_state_keeps_previous_final_values(self):
        states = iter((BallState(4, 5, True, 1), BallState(99, 99, False, 2),
                       BallState(float("nan"), 8, True, 3)))
        builder = BallStateBuilder(state_source=lambda _: next(states))
        self.assertEqual(builder.update(result()), BallState(4, 5, True, 1))
        self.assertEqual(builder.update(result()), BallState(4, 5, False, 2))
        self.assertEqual(builder.update(result()), BallState(4, 5, False, 3))
