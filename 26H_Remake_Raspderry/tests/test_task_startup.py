"""Common startup remains unchanged when mode-specific tasks are added."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ballbeam.app.arguments import parse_runtime_args
from ballbeam.app import task_startup
from ballbeam.communication.protocol import Mode
from ballbeam.errors import RuntimeIOError


class TaskStartupTests(unittest.TestCase):
    def parse(self, argv):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return parse_runtime_args(argv)

    def test_default_and_legacy_speed_commands_select_registered_tasks(self):
        mode, number, task = task_startup.select_task(self.parse([]))
        self.assertEqual((mode, number, task.label), (Mode.RUN, 1, "Task1"))
        args = self.parse(["--task-console", "--task1-csv", "control.csv", "--velocity-test", "-2"])
        mode, number, task = task_startup.select_task(args)
        self.assertEqual((mode, number), (Mode.TUNING, 1))
        self.assertIs(task.initialize, task_startup.initialize_velocity_test)

    def test_same_task_id_can_have_different_meanings_in_each_mode(self):
        other = task_startup.TaskSpec("another debug experiment")
        with patch.dict(task_startup.TASKS[Mode.TUNING], {1: other}):
            selected = task_startup.select_task(self.parse(["--mode", "tuning", "--task-id", "1"]))
        self.assertEqual(selected, (Mode.TUNING, 1, other))
        self.assertIsNone(selected[2].initialize)

    def test_new_task_requires_registration_not_new_startup_branches(self):
        prepare, validate = Mock(), Mock()
        spec = task_startup.TaskSpec("experiment seven", prepare, validate)
        with patch.dict(task_startup.TASKS[Mode.TUNING], {7: spec}):
            args = self.parse(["--mode", "tuning", "--task-id", "7", "--task-console"])
            mode, number, selected = task_startup.select_task(args)
        self.assertEqual((mode, number), (Mode.TUNING, 7))
        client, capture = Mock(), Mock()
        events = []
        client.request_task.side_effect = lambda n: events.append(("initialize", n)) or 1
        client.task_result.return_value = True
        prepare.side_effect = lambda *_: events.append(("prepare", number))
        with patch.object(task_startup, "wait_for_operator_start",
                          side_effect=lambda n: events.append(("operator", n))):
            task_startup.initialize_task_startup(client, args, capture, task_id=number, task=selected)
        self.assertEqual(events, [("initialize", 0), ("prepare", 7), ("operator", 7)])
        prepare.assert_called_once_with(client, args, capture)
        validate.assert_called_with(args)
        client.request_task.assert_called_once_with(0)

    def test_velocity_validation_follows_registration_not_hardcoded_task_number(self):
        spec = task_startup.TASKS[Mode.TUNING][1]
        with patch.dict(task_startup.TASKS[Mode.TUNING], {7: spec}):
            args = self.parse(["--mode", "tuning", "--task-id", "7", "--task-console",
                               "--task1-csv", "control.csv", "--velocity-test", "2"])
            self.assertEqual(task_startup.select_task(args)[:2], (Mode.TUNING, 7))

    def test_other_tuning_task_does_not_require_velocity_options_or_capture(self):
        spec = task_startup.TaskSpec("another tuning task")
        with patch.dict(task_startup.TASKS[Mode.TUNING], {7: spec}):
            args = self.parse(["--mode", "tuning", "--task-id", "7", "--task-console"])
            self.assertEqual(task_startup.select_task(args), (Mode.TUNING, 7, spec))

    def test_cli_rejects_unknown_tasks_initialization_as_motion_and_conflicts(self):
        cases = (
            ["--mode", "task"], ["--mode", "debug"],
            ["--mode", "run", "--task-id", "2"],
            ["--task-id", "0"], ["--task-id", "15"],
            ["--mode", "tuning", "--task-console"],
            ["--mode", "run", "--task-console", "--task1-csv", "control.csv", "--velocity-test", "2"],
        )
        for argv in cases:
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.parse(argv)

    def test_operator_confirmation_accepts_any_registered_task_number(self):
        with patch.object(task_startup.sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", side_effect=["task 1", "task 7"]) as prompt, \
             redirect_stdout(io.StringIO()):
            task_startup.wait_for_operator_start(7)
        self.assertEqual(prompt.call_count, 2)
        self.assertIn("task 7", prompt.call_args.args[0])

    def test_initialization_failure_stops_before_preparation_or_operator(self):
        client, capture, prepare = Mock(), Mock(), Mock()
        client.request_task.return_value = 1
        client.task_result.return_value = False
        with patch.object(task_startup, "wait_for_operator_start") as operator:
            with self.assertRaises(RuntimeIOError):
                task_startup.initialize_task_startup(client, SimpleNamespace(task_console=True), capture,
                    task_id=7, task=task_startup.TaskSpec("test", prepare))
        operator.assert_not_called()
        prepare.assert_not_called()

    def test_disabled_task_startup_has_no_motion_or_preparation(self):
        client, capture, prepare = Mock(), Mock(), Mock()
        with patch.object(task_startup, "wait_for_operator_start") as operator:
            task_startup.initialize_task_startup(client, SimpleNamespace(task_console=False), capture,
                task_id=7, task=task_startup.TaskSpec("test", prepare))
        self.assertEqual(client.mock_calls, [])
        prepare.assert_not_called()
        operator.assert_not_called()

    def test_velocity_preparation_saves_settings_only_after_confirmation(self):
        args = self.parse(["--mode", "tuning", "--task-id", "1", "--task-console",
                           "--task1-csv", "control.csv", "--velocity-test", "-5"])
        client, capture = Mock(), Mock()
        client.set_velocity_parameters.return_value = 4
        client.parameters_result.return_value = True
        with redirect_stdout(io.StringIO()):
            task_startup.initialize_velocity_test(client, args, capture)
        client.set_velocity_parameters.assert_called_once_with(.5, 0, 0, -5)
        client.parameters_result.assert_called_once_with(4)
        filename, data = capture.save_settings.call_args.args
        self.assertEqual(filename, "velocity_settings.json")
        self.assertEqual((data["task_id"], data["target_velocity_cm_s"]), (1, -5))
        self.assertTrue(data["pid_applied_telemetry"])
        capture.reset_mock()
        client.parameters_result.return_value = False
        with self.assertRaises(RuntimeIOError):
            task_startup.initialize_velocity_test(client, args, capture)
        capture.save_settings.assert_not_called()

    def test_mode_and_task_can_be_selected_from_toml_and_overridden_on_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.toml"
            path.write_text('version = 1\n[formal_tracking]\nmode = "tuning"\ntask_id = 1\n', encoding="utf-8")
            args = self.parse(["--config", str(path)])
            self.assertEqual(task_startup.select_task(args)[:2], (Mode.TUNING, 1))
            args = self.parse(["--config", str(path), "--mode", "run", "--task-id", "1"])
            self.assertEqual(task_startup.select_task(args)[:2], (Mode.RUN, 1))
