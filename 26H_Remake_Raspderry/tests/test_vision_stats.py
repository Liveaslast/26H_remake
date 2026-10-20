"""One source of vision rates for both console output and image overlays."""

from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from ballbeam.interfaces.presentation import format_vision_stats
from ballbeam.vision.angles import FrameAngle
from ballbeam.app.tracking import run_tracking_loop
from ballbeam.vision.metrics import VisionStats


def result(**updates):
    fields = dict(measurement_valid=True, source="yolo_box", inference_ms=10.0,
                  processing_ms=15.0)
    fields.update(updates)
    return SimpleNamespace(**fields)


class VisionStatsTests(unittest.TestCase):
    def test_first_sample_has_timings_but_no_rate(self):
        metrics = VisionStats().update(0, result())
        self.assertIsNone(metrics.fps)
        self.assertIsNone(metrics.valid_detection_hz)
        self.assertEqual(metrics.average_inference_ms, 10)
        self.assertEqual(metrics.average_processing_ms, 15)

    def test_all_valid_results_share_fps_rate_without_off_by_one(self):
        stats = VisionStats()
        stats.update(0, result())
        stats.update(.5, result())
        metrics = stats.update(1, result())
        self.assertEqual(metrics.fps, 2)
        self.assertEqual(metrics.valid_detection_hz, 2)

    def test_failed_inference_counts_in_average_not_valid_detection_rate(self):
        stats = VisionStats()
        stats.update(0, result())
        metrics = stats.update(.5, result(measurement_valid=False, source="lost",
                                         inference_ms=30, processing_ms=35))
        self.assertEqual(metrics.fps, 2)
        self.assertEqual(metrics.valid_detection_hz, 0)
        self.assertEqual(metrics.average_inference_ms, 20)
        self.assertEqual(metrics.average_processing_ms, 25)

    def test_flow_result_is_not_a_model_detection(self):
        stats = VisionStats()
        stats.update(0, result())
        metrics = stats.update(.5, result(source="optical_flow", inference_ms=0))
        self.assertEqual(metrics.valid_detection_hz, 0)
        self.assertEqual(metrics.average_inference_ms, 10)

    def test_no_inference_has_no_inference_average(self):
        metrics = VisionStats().update(0, result(inference_ms=0))
        self.assertIsNone(metrics.average_inference_ms)
        text = format_vision_stats(metrics)
        self.assertIn("valid_detect_hz=warming", text)
        self.assertIn("avg_infer=warming", text)
        self.assertNotIn("track_hz", text)
        self.assertNotIn("loop_hz", text)

    def test_window_discards_old_samples(self):
        stats = VisionStats(window_seconds=1)
        stats.update(0, result(inference_ms=100))
        stats.update(.5, result())
        metrics = stats.update(1.1, result())
        self.assertAlmostEqual(metrics.fps, 1 / .6)
        self.assertEqual(metrics.average_inference_ms, 10)

    def test_buffer_capacity_is_bounded(self):
        stats = VisionStats(window_seconds=10, maximum_samples=2)
        stats.update(0, result(inference_ms=100))
        stats.update(.1, result())
        metrics = stats.update(.2, result())
        self.assertEqual(len(stats._events), 2)
        self.assertEqual(metrics.average_inference_ms, 10)
        self.assertAlmostEqual(metrics.fps, 10)

    def test_nonincreasing_time_resets_observation_window(self):
        stats = VisionStats()
        stats.update(1, result())
        self.assertIsNone(stats.update(1, result()).fps)
        self.assertIsNone(stats.update(.5, result()).fps)
        self.assertEqual(stats.update(1, result()).fps, 2)

    def test_invalid_window_and_timestamp_are_rejected(self):
        for window in (0, -1, float("nan"), float("inf")):
            with self.subTest(window=window), self.assertRaises(ValueError):
                VisionStats(window_seconds=window)
        with self.assertRaises(ValueError):
            VisionStats(maximum_samples=1)
        with self.assertRaises(ValueError):
            VisionStats().update(float("nan"), result())

    def test_loop_passes_same_fps_to_console_and_overlay(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        camera, tracker = Mock(), Mock()
        camera.read.side_effect = [(frame, 0), (frame, 1)]
        tracker.process.return_value = result()
        args = SimpleNamespace(duration=0, warmup_frames=0, report_period=.5, no_display=False)
        with patch("ballbeam.app.tracking.time.perf_counter", side_effect=[0, 0, 1]), \
             patch("ballbeam.interfaces.presentation.format_result", return_value="result") as console, \
             patch("ballbeam.interfaces.presentation.draw_tracking_overlay", return_value=frame) as overlay, \
             patch("ballbeam.interfaces.presentation.cv2.imshow"), \
             patch("ballbeam.interfaces.presentation.cv2.waitKeyEx", side_effect=[-1, 27]), \
             patch("ballbeam.interfaces.presentation.cv2.destroyAllWindows"), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(run_tracking_loop(
                SimpleNamespace(camera=camera, tracker=tracker), args,
                angle_for_frame=lambda timestamp: FrameAngle(21), window_name="test",
            ), 0)
        self.assertEqual([call.kwargs["fps"] for call in console.call_args_list], [None, 1])
        self.assertEqual([call.kwargs["fps"] for call in overlay.call_args_list], [None, 1])
        camera.close.assert_called_once()
