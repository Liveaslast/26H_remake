"""Motor-angle lookup, gap handling, calibration limits and warning drawing."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from ballbeam.vision.angles import AngleHistory, interpolate_angle_samples
from ballbeam.interfaces.presentation import draw_missing_angle
from ballbeam.vision.angles import FrameAngleSource


class FrameAngleTests(unittest.TestCase):
    def test_interpolation_between_nearby_samples(self):
        reading = interpolate_angle_samples(((1.0, 12), (1.1, 30)), 1.05, .1)
        self.assertAlmostEqual(reading.angle_deg, 21)

    def test_large_gap_uses_nearest_real_sample_not_interpolation(self):
        reading = interpolate_angle_samples(((0.0, 12), (10.0, 30)), 9.99, .1)
        self.assertEqual(reading.angle_deg, 30)
        self.assertEqual(reading.received_monotonic, 10.0)

    def test_middle_of_large_gap_is_invalid(self):
        self.assertIsNone(interpolate_angle_samples(((0.0, 12), (10.0, 30)), 5, .1))

    def test_before_and_after_history_respect_age_limit(self):
        samples = ((1.0, 12), (1.1, 30))
        self.assertEqual(interpolate_angle_samples(samples, .99, .1).angle_deg, 12)
        self.assertEqual(interpolate_angle_samples(samples, 1.11, .1).angle_deg, 30)
        self.assertIsNone(interpolate_angle_samples(samples, 2.0, .1))

    def test_nonfinite_record_is_not_saved(self):
        angles = AngleHistory()
        angles.record(SimpleNamespace(actual_angle_deg=float("nan"), received_monotonic=1.0))
        self.assertIsNone(angles.angle_at(1.0, maximum_age_seconds=.1))

    def make_source(self, angle, clamp=True):
        angles = Mock()
        angles.angle_at.return_value = None if angle is None else SimpleNamespace(angle_deg=angle)
        return FrameAngleSource(angles, maximum_age_seconds=.1, camera_latency_seconds=.02,
                                calibration_range=(12, 30), clamp=clamp)

    def test_lookup_subtracts_camera_latency(self):
        source = self.make_source(21)
        self.assertEqual(source.for_frame(1).angle_deg, 21)
        source.angles.angle_at.assert_called_once_with(.98, maximum_age_seconds=.1)

    def test_missing_angle_is_invalid(self):
        decision = self.make_source(None).for_frame(1)
        self.assertIsNone(decision.angle_deg)
        self.assertEqual(decision.invalid_reason, "angle-telemetry-stale")

    def test_clamp_retains_warning_and_no_clamp_delegates_to_calibration(self):
        decision = self.make_source(35).for_frame(1)
        self.assertEqual(decision.angle_deg, 30)
        self.assertIn("angle-clamped", decision.report_prefix)
        self.assertEqual(self.make_source(35, clamp=False).for_frame(1).angle_deg, 35)

    def test_warning_overlay_accepts_loop_callback_signature_and_preserves_frame(self):
        frame = np.zeros((100, 400, 3), dtype=np.uint8)
        canvas = draw_missing_angle(frame, SimpleNamespace(reason="angle-telemetry-stale"), 60)
        self.assertEqual(canvas.shape, frame.shape)
        self.assertGreater(canvas.sum(), 0)
        self.assertEqual(frame.sum(), 0)
