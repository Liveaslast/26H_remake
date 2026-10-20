"""Vision processing, console reporting and display have independent interfaces."""

from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from ballbeam.interfaces.presentation import TrackingDisplay, VisionReporter
from ballbeam.vision.angles import FrameAngle
from ballbeam.app.tracking import process_frame, run_tracking_loop
from ballbeam.vision.calibration import DynamicCalibrationError


class VisionInterfaceTests(unittest.TestCase):
    def test_processing_uses_matched_angle_and_preserves_result(self):
        tracker = Mock()
        frame = np.zeros((10, 10, 3), np.uint8)
        result = process_frame(tracker, frame, 2, FrameAngle(21))
        self.assertIs(result, tracker.process.return_value)
        tracker.process.assert_called_once_with(frame, 21, 2)
        tracker.process_missing_angle.assert_not_called()

    def test_missing_angle_does_not_run_detection(self):
        tracker = Mock()
        process_frame(tracker, None, 2, FrameAngle(None, "stale"))
        tracker.process.assert_not_called()
        tracker.process_missing_angle.assert_called_once_with(2, "stale")

    def test_rectification_error_becomes_invalid_result_but_model_error_propagates(self):
        tracker = Mock()
        tracker.process.side_effect = DynamicCalibrationError("outside calibration")
        process_frame(tracker, None, 2, FrameAngle(21))
        tracker.process_missing_angle.assert_called_once_with(
            2, "rectification-invalid:outside calibration")
        tracker.process.side_effect = RuntimeError("model failed")
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            process_frame(tracker, None, 2, FrameAngle(21))

    def test_reporter_controls_cadence_without_recomputing_metrics(self):
        reporter = VisionReporter(.5)
        metrics = SimpleNamespace(fps=20)
        with patch("ballbeam.interfaces.presentation.format_result", return_value="result") as formatted, \
             patch("ballbeam.interfaces.presentation.format_vision_stats", return_value="stats") as stats, \
             redirect_stdout(io.StringIO()) as output:
            for now in (1, 1.1, 1.5):
                reporter.report(now, "sample", FrameAngle(21, report_prefix="clamped "), metrics)
        self.assertEqual(formatted.call_count, 2)
        self.assertEqual(stats.call_count, 2)
        formatted.assert_called_with("sample", fps=20)
        self.assertEqual(output.getvalue().splitlines(), ["clamped result stats"] * 2)

    def test_headless_display_does_not_touch_highgui_or_render(self):
        with patch("ballbeam.interfaces.presentation.cv2.imshow") as show, \
             patch("ballbeam.interfaces.presentation.cv2.destroyAllWindows") as close, \
             patch("ballbeam.interfaces.presentation.draw_tracking_overlay") as draw:
            display = TrackingDisplay("unused", enabled=False)
            self.assertTrue(display.show(None, None, None, None))
            display.close()
        show.assert_not_called()
        close.assert_not_called()
        draw.assert_not_called()

    def test_missing_overlay_uses_copy_of_last_canvas_and_preserves_cache(self):
        frame = np.zeros((20, 20, 3), np.uint8)
        canvas = np.ones_like(frame)
        def fallback(image, result, fps):
            image[0, 0] = 9
            return image
        display = TrackingDisplay("test", hold_last=True, fallback_overlay=fallback)
        with patch("ballbeam.interfaces.presentation.draw_tracking_overlay", side_effect=[canvas, None]), \
             patch("ballbeam.interfaces.presentation.cv2.imshow") as show, \
             patch("ballbeam.interfaces.presentation.cv2.waitKeyEx", side_effect=[-1, 27]):
            self.assertTrue(display.show(frame, "valid", FrameAngle(21), 20))
            self.assertFalse(display.show(frame, "invalid", FrameAngle(None), 20))
        np.testing.assert_array_equal(display.last_canvas, canvas)
        self.assertTrue(np.all(show.call_args.args[1][0, 0] == 9))
        self.assertTrue(np.all(frame == 0))

    def test_keyboard_hook_is_separate_from_exit_keys(self):
        hook = Mock()
        display = TrackingDisplay("test", key_handler=hook)
        frame = np.zeros((20, 20, 3), np.uint8)
        with patch("ballbeam.interfaces.presentation.draw_tracking_overlay", return_value=frame), \
             patch("ballbeam.interfaces.presentation.cv2.imshow"), \
             patch("ballbeam.interfaces.presentation.cv2.waitKeyEx", side_effect=[ord("s"), ord("q")]):
            self.assertTrue(display.show(frame, None, None, 10))
            self.assertFalse(display.show(frame, None, None, 10))
        hook.assert_called_once_with(ord("s"))

    def test_camera_and_display_are_closed_when_processing_raises(self):
        camera, tracker = Mock(), Mock()
        camera.read.return_value = (None, 1)
        tracker.process.side_effect = RuntimeError("model failed")
        args = SimpleNamespace(duration=0, report_period=.5, warmup_frames=0, no_display=False)
        with patch("ballbeam.app.tracking.TrackingDisplay") as display:
            with self.assertRaisesRegex(RuntimeError, "model failed"):
                run_tracking_loop(SimpleNamespace(camera=camera, tracker=tracker), args,
                                  angle_for_frame=lambda t: FrameAngle(21), window_name="test")
        camera.close.assert_called_once()
        display.return_value.close.assert_called_once()
