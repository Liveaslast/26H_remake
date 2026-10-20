"""Recording window coordination without owning communication callbacks."""

import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from ballbeam.recording.capture import CaptureSession
from ballbeam.vision.ball_state import BallState


def args(directory, **updates):
    fields = dict(task1_csv=Path(directory) / "control.csv", task1_capture_s=60.0,
                  velocity_test=2.0, velocity_kp=.5, velocity_ki=.1, velocity_kd=0,
                  vision_probe_csv=Path(directory) / "vision_probe.csv",
                  vision_probe_print=False)
    fields.update(updates)
    return SimpleNamespace(**fields)


class CaptureTests(unittest.TestCase):
    def test_disabled_capture_creates_no_recorders(self):
        capture = CaptureSession(args("unused", task1_csv=None, vision_probe_csv=None))
        capture.open()
        self.assertIsNone(capture.control)
        self.assertIsNone(capture.sent)
        self.assertIsNone(capture.probe)
        capture.start()
        self.assertFalse(capture.finish_if_needed())
        capture.close()

    def test_finished_window_reports_transition_and_closes_probe_once(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = CaptureSession(args(directory))
            try:
                capture.open()
                self.assertIs(capture.control.output._worker, capture.writer)
                self.assertIs(capture.sent.output._worker, capture.writer)
                self.assertIs(capture.probe.output._worker, capture.writer)
                probe = capture.probe
                capture.start()
                capture.control.close()
                self.assertTrue(capture.finish_if_needed())
                self.assertFalse(capture.finish_if_needed())
                self.assertIsNone(capture.probe)
                self.assertTrue(probe.output.closed)
                self.assertTrue(capture.sent.output.closed)
            finally:
                capture.close()
            self.assertFalse(capture.writer._thread.is_alive())

    def test_metadata_filename_and_fields_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = args(directory)
            capture = CaptureSession(settings)
            try:
                capture.open()
                capture.save_settings("velocity_settings.json", {
                    "task_id": 2, "target_velocity_cm_s": 2,
                    "safety_timeout_ms": 8000, "pid_applied_telemetry": True,
                })
                data = json.loads((Path(directory) / "velocity_settings.json").read_text())
                self.assertEqual(data["task_id"], 2)
                self.assertEqual(data["target_velocity_cm_s"], 2)
                self.assertEqual(data["safety_timeout_ms"], 8000)
                self.assertTrue(data["pid_applied_telemetry"])
            finally:
                capture.close()

    def test_probe_csv_keeps_measurement_and_filtered_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = CaptureSession(args(directory, task1_csv=None))
            try:
                capture.open()
                sample = SimpleNamespace(timestamp=1.0, position_cm=2.0, velocity_cm_s=3.0,
                    center_px=(100, 50), radius_px=5, actual_angle_deg=21,
                    measurement_position_cm=2.5, measurement_valid=True, tracking_valid=True,
                    inference_ms=10, refinement_ms=0, processing_ms=12, confidence=.9,
                    source="detection", reason="ok")
                capture.record_vision(sample, BallState(2.5, 3, True, 1.0))
            finally:
                capture.close()
            with (Path(directory) / "vision_probe.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["raw_x_cm"], "2.0000")
            self.assertEqual(rows[0]["measurement_x_cm"], "2.5000")
            self.assertEqual(rows[0]["sent_x_cm"], "2.5000")

    def test_partial_open_failure_still_allows_closing_control_file(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = CaptureSession(args(directory))
            from unittest.mock import patch
            with patch("ballbeam.recording.capture.BallStateTxLogger", side_effect=OSError("disk full")):
                try:
                    with self.assertRaises(OSError):
                        capture.open()
                finally:
                    capture.close()
            self.assertTrue(capture.control.finished)
