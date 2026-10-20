"""Exercise physical measurement selection, temporal state and pipeline wiring separately."""

import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from ballbeam.vision import tracker as module
from ballbeam.vision.tracker import (
    BallMeasurement, CandidateSelector, DynamicBallTracker, DynamicTrackerConfig,
    TrackingState,
)
from ballbeam.vision.detection_runtime.models import AdaptiveFrameDetection, BallDetection
from ballbeam.interfaces.presentation import draw_tracking_overlay


def ball(x=100, y=50, confidence=.9, source="yolo_box"):
    return BallDetection((x - 5, y - 5, x + 5, y + 5), confidence, 0, (x, y), 5, source)


def detections(*balls):
    return AdaptiveFrameDetection(tuple(balls), 2, 0, 0, 0, 1)


class TrackerStageTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((100, 200, 3), np.uint8)
        self.geometry = SimpleNamespace(pixel_to_cm=lambda u: (u - 100) / 10)
        self.calibration = Mock(canonical_size=(200, 100))
        self.calibration.rectify.return_value = self.frame, self.geometry
        self.config = DynamicTrackerConfig(measurement_center="bbox")

    def measurement(self, x=100):
        return CandidateSelector(self.calibration, self.config).select(detections(ball(x)), self.geometry)

    def test_selector_maps_pixels_and_rejects_noise_without_temporal_state(self):
        selector = CandidateSelector(self.calibration, self.config)
        chosen = selector.select(detections(ball(110), ball(100, 0), ball(100, confidence=.1)), self.geometry)
        self.assertEqual(chosen.position_cm, 1)
        self.assertEqual(chosen.center_px, (110, 50))
        self.assertFalse(hasattr(selector, "kalman"))
        self.assertFalse(hasattr(selector, "_last_measurement_timestamp"))

    def test_selector_uses_only_explicit_prediction_for_association(self):
        selector = CandidateSelector(self.calibration, self.config)
        self.assertIsNone(selector.select(detections(ball(180)), self.geometry,
                                         predicted_position=0, lost_seconds=.01))
        self.assertIsNotNone(selector.select(detections(ball(180)), self.geometry,
                                            predicted_position=0, lost_seconds=.2))

    def test_bbox_and_refined_centers_remain_distinct_measurement_policies(self):
        observation = replace(ball(100, source="ransac"), center_px=(110, 50))
        bbox = CandidateSelector(self.calibration, self.config).select(detections(observation), self.geometry)
        refined = CandidateSelector(self.calibration, replace(self.config, measurement_center="refined"))
        result = refined.select(detections(observation), self.geometry)
        self.assertEqual((bbox.position_cm, bbox.source), (0, "yolo_box"))
        self.assertEqual((result.position_cm, result.source), (1, "ransac"))

    def test_default_state_does_not_create_or_apply_optional_filters(self):
        state = TrackingState(self.config)
        self.assertIsNone(state.kalman)
        self.assertIsNone(state.velocity_lowpass)
        first = state.observe(self.measurement(110), 1)
        second = state.observe(self.measurement(120), 1.02)
        self.assertFalse(first.tracking_valid)
        self.assertTrue(second.tracking_valid)
        self.assertEqual((second.position_cm, second.velocity_cm_s), (2, 0))

    def test_state_handles_loss_and_reconfirmation_without_geometry_or_detector(self):
        state = TrackingState(self.config)
        measurement = self.measurement()
        state.observe(measurement, 1)
        state.observe(measurement, 1.02)
        self.assertTrue(state.observe(None, 1.05).tracking_valid)
        self.assertFalse(state.observe(None, 1.2).tracking_valid)
        state.reset()
        self.assertFalse(state.observe(measurement, 2).tracking_valid)

    def test_optional_estimation_remains_behind_state_interface(self):
        state = TrackingState(replace(self.config, enable_kalman=True, confirmation_hits=1))
        state.begin_frame(1)
        state.predict(1, 21)
        first = state.observe(self.measurement(100), 1)
        state.begin_frame(1.02)
        state.predict(1.02, 21)
        second = state.observe(self.measurement(101), 1.02)
        self.assertTrue(first.tracking_valid)
        self.assertTrue(second.tracking_valid)
        self.assertIsNotNone(second.velocity_cm_s)
        state.begin_frame(2)
        state.predict(2, 21)
        self.assertFalse(state.observe(None, 2).tracking_valid)
        self.assertIsNone(state.predicted_position)

    def test_pipeline_returns_measurement_and_original_timing_contract(self):
        detector = Mock(detect=Mock(return_value=detections(ball(110))))
        tracker = DynamicBallTracker(self.calibration, detector, self.config)
        result = tracker.process(self.frame, 21, 1)
        self.calibration.rectify.assert_called_once_with(self.frame, 21)
        detector.detect.assert_called_once_with(self.frame)
        self.assertEqual((result.measurement_position_cm, result.position_cm), (1, 1))
        self.assertEqual(result.inference_ms, 2)
        self.assertTrue(result.measurement_valid)
        self.assertFalse(result.tracking_valid)
        self.assertTrue(tracker.process(self.frame, 21, 1.02).tracking_valid)

    def test_pipeline_accepts_replacement_measurement_selector_without_changing_detector(self):
        measurement = BallMeasurement(ball(), 3, .9, (100, 50), "yolo_box", 5)
        selector = Mock(select=Mock(return_value=measurement))
        detector = Mock(detect=Mock(return_value=detections()))
        tracker = DynamicBallTracker(self.calibration, detector, self.config, selector=selector)
        result = tracker.process(self.frame, 21, 1)
        self.assertEqual(result.measurement_position_cm, 3)
        selector.select.assert_called_once_with(detector.detect.return_value, self.geometry,
                                               predicted_position=None, lost_seconds=None)

    def test_pipeline_accepts_replacement_state_and_resets_only_state(self):
        state = Mock(predicted_position=None)
        state.lost_seconds.return_value = None
        state.observe.return_value = module.TrackingStatus(1, 2, True, 0, "yolo_box", "ok")
        detector = Mock(detect=Mock(return_value=detections(ball(110))))
        tracker = DynamicBallTracker(self.calibration, detector, self.config, state=state)
        result = tracker.process(self.frame, 21, 1)
        state.begin_frame.assert_called_once_with(1)
        state.predict.assert_called_once_with(1, 21)
        self.assertEqual((result.position_cm, result.velocity_cm_s), (1, 2))
        tracker.reset()
        state.reset.assert_called_once()
        self.assertEqual(detector.detect.call_count, 1)

    def test_missing_angle_never_runs_geometry_or_detection_and_invalidates_state(self):
        detector = Mock()
        tracker = DynamicBallTracker(self.calibration, detector, self.config)
        result = tracker.process_missing_angle(1)
        self.assertFalse(result.tracking_valid)
        self.assertFalse(result.measurement_valid)
        self.calibration.rectify.assert_not_called()
        detector.detect.assert_not_called()

    def test_overlay_is_outside_domain_and_does_not_mutate_result_image(self):
        tracker = DynamicBallTracker(self.calibration, Mock(detect=Mock(return_value=detections(ball()))), self.config)
        result = tracker.process(self.frame, 21, 1)
        canvas = draw_tracking_overlay(result, fps=30)
        self.assertEqual(canvas.shape, (172, 200, 3))
        self.assertTrue(canvas.any())
        self.assertFalse(self.frame.any())
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        self.assertNotIn("draw_tracking_overlay", [getattr(node, "name", None) for node in tree.body])
        self.assertNotIn("import cv2", Path(module.__file__).read_text(encoding="utf-8"))
