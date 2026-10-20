"""Keep entry-point orchestration separate from domain and device code."""

import ast
from contextlib import redirect_stderr
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ballbeam.app import main
from ballbeam.app.arguments import parse_runtime_args
from ballbeam.errors import RuntimeIOError


class AppBoundaryTests(unittest.TestCase):
    def test_main_does_not_define_argument_parser_or_draw_warning(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(functions, {"run", "main"})
        self.assertNotIn("add_argument(", source)
        self.assertNotIn("cv2.putText", source)

    def test_ball_state_does_not_import_communication_or_file_recorders(self):
        from ballbeam.vision import ball_state
        source = Path(ball_state.__file__).read_text(encoding="utf-8")
        imports = [node.module for node in ast.walk(ast.parse(source))
                   if isinstance(node, ast.ImportFrom)]
        self.assertEqual(imports, ["dataclasses", "tracker"])

    def test_loop_orchestrates_instead_of_rendering_or_formatting(self):
        from ballbeam.app import tracking
        tree = ast.parse(Path(tracking.__file__).read_text(encoding="utf-8"))
        loop = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "run_tracking_loop")
        source = ast.unparse(loop)
        for detail in ("cv2.", "print(", "format_result(", "last_display_canvas"):
            self.assertNotIn(detail, source)
        self.assertIn("reporter.report(", source)
        self.assertIn("display.show(", source)

    def test_capture_and_recorders_do_not_own_client_connections_or_scp(self):
        from ballbeam.recording import capture, csv_recorders
        source = Path(capture.__file__).read_text(encoding="utf-8")
        self.assertNotIn("client.", source)
        self.assertNotIn("communication", source)
        source = Path(csv_recorders.__file__).read_text(encoding="utf-8")
        self.assertNotIn("scp ", source)
        self.assertNotIn("192.168.", source)

    def test_hailort_does_not_depend_on_ncnn_private_helpers(self):
        path = Path(main.__file__).parents[1] / "vision/detection_runtime/hailort_backend.py"
        imports = [node.module for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                   if isinstance(node, ast.ImportFrom)]
        self.assertNotIn("ncnn_backend", imports)
        self.assertIn("preprocessing", imports)

    def test_removed_pre_transmission_filter_options_are_not_accepted(self):
        options = (
            "--ball-position-lowpass-tau-ms", "--ball-position-median-window",
            "--ball-position-deadband-cm", "--ball-position-slew-limit-cm-s",
            "--ball-position-jump-threshold-cm", "--ball-position-jump-confirm-ms",
            "--ball-ignore-zero-position-cm", "--ball-velocity-lowpass-tau-ms",
            "--ball-velocity-deadband-cm-s",
        )
        with redirect_stderr(io.StringIO()):
            for option in options:
                with self.subTest(option=option), self.assertRaises(SystemExit):
                    parse_runtime_args([option, "1"])

    def test_cli_rejects_invalid_speed_and_keeps_display_switches(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_runtime_args(["--velocity-test", "6", "--task-console", "--task1-csv", "control.csv"])
        self.assertTrue(parse_runtime_args(["--no-display"]).no_display)
        self.assertFalse(parse_runtime_args(["--display"]).no_display)

    def test_mode_rejection_stops_client_without_starting_camera(self):
        args = parse_runtime_args([])
        client = Mock()
        client.select_mode.return_value = False
        components = SimpleNamespace(calibration=SimpleNamespace(angle_range_deg=(12, 30)))
        with patch.object(main, "McuSerialClient", return_value=client), \
             patch.object(main, "build_tracking_components", return_value=components), \
             patch.object(main, "run_tracking_loop") as tracking:
            with self.assertRaises(RuntimeIOError):
                main.run(args)
        client.stop_stream.assert_called_once()
        client.stop.assert_called_once()
        tracking.assert_not_called()

    def test_capture_failure_stops_client_and_closes_partial_capture(self):
        args = parse_runtime_args([])
        client = Mock()
        client.select_mode.return_value = True
        components = SimpleNamespace(calibration=SimpleNamespace(angle_range_deg=(12, 30)))
        capture = Mock()
        capture.open.side_effect = OSError("disk full")
        with patch.object(main, "McuSerialClient", return_value=client), \
             patch.object(main, "build_tracking_components", return_value=components), \
             patch.object(main, "wait_for_first_angle", return_value=SimpleNamespace(angle_deg=21)), \
             patch.object(main, "CaptureSession", return_value=capture):
            with self.assertRaises(OSError):
                main.run(args)
        client.stop.assert_called_once()
        capture.close.assert_called_once()

    def test_application_detaches_callbacks_and_reports_finished_capture(self):
        args = parse_runtime_args([])
        args.debug_page = args.wifi_stream = False
        client, capture, tasks = Mock(), Mock(), Mock()
        tasks.start_if_ready.return_value = False
        capture.finish_if_needed.side_effect = [True, False]
        components = SimpleNamespace(calibration=SimpleNamespace(angle_range_deg=(12, 30)))
        result = SimpleNamespace(timestamp=0, measurement_position_cm=1,
                                 measurement_valid=True, tracking_valid=True,
                                 position_cm=1, velocity_cm_s=2, actual_angle_deg=21)

        def track(_components, _args, **handlers):
            handlers["result_handler"](result)
            handlers["result_handler"](result)
            self.assertIsNone(client.record_control_sample)
            self.assertIsNone(client.record_sent_frame)
            return 0

        with patch.object(main, "McuSerialClient", return_value=client), \
             patch.object(main, "build_tracking_components", return_value=components), \
             patch.object(main, "CaptureSession", return_value=capture), \
             patch.object(main, "TaskRunner", return_value=tasks), \
             patch.object(main, "wait_for_first_angle", return_value=SimpleNamespace(angle_deg=21)), \
             patch.object(main, "report_capture_finished") as report, \
             patch.object(main, "run_tracking_loop", side_effect=track):
            self.assertEqual(main.run(args), 0)
        report.assert_called_once_with(capture.control)
        capture.finish_if_needed.assert_called_with()
        self.assertEqual(client.publish_ball_state.call_count, 2)
