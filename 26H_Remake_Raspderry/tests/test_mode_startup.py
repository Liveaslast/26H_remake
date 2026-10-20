"""Exercise the real application startup wiring with a fake serial MCU."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ballbeam.app import main
from ballbeam.app.arguments import parse_runtime_args
from ballbeam.app import task_startup
from ballbeam.communication.client import McuSerialClient
from ballbeam.communication.protocol import Mode, decode_pi_frame, PI_TUNING_FRAME
from fake_mcu import FakeSerial, mode_reply, telemetry, wait_until


class ModeStartupTests(unittest.TestCase):
    def run_mode(self, tuning, explicit=False):
        port = FakeSerial()
        client = McuSerialClient("unused", 115200,
                                 read_timeout_seconds=.001, write_timeout_seconds=.01)
        selected = Mode.NONE

        def receive(frame):
            nonlocal selected
            if frame[1] == 6:
                selected = Mode(frame[4])
                port.incoming.put(mode_reply(int.from_bytes(frame[2:4], "little"), selected))
                return
            packet = decode_pi_frame(frame)
            self.assertEqual(packet.mode, selected)
            revision = PI_TUNING_FRAME.unpack(frame)[-2] if tuning else 0
            port.incoming.put(telemetry(status=24, angle=2100, mode=selected,
                                        request_seq=packet.request_seq, revision=revision))
        port.on_write = receive

        def track(_components, _args, **handlers):
            import time
            result = SimpleNamespace(tracking_valid=True, measurement_valid=True,
                                     timestamp=time.monotonic(), measurement_position_cm=0,
                                     position_cm=0, velocity_cm_s=0, actual_angle_deg=21)
            handler = handlers["result_handler"]
            handler(result)
            wait_until(lambda: client.visual_state_sent)
            handler(result)
            wait_until(lambda: client.task_result(client.session.stream.request_seq) is True)
            handler(result)
            return 0

        with tempfile.TemporaryDirectory() as directory:
            argv = ["--task-console"]
            if explicit:
                argv += ["--mode", "tuning" if tuning else "run", "--task-id", "1"]
            if tuning:
                argv += ["--velocity-test", "2", "--task1-csv", str(Path(directory) / "control.csv")]
            args = parse_runtime_args(argv)
            args.debug_page = args.wifi_stream = False
            components = SimpleNamespace(calibration=SimpleNamespace(angle_range_deg=(12, 30)))
            with patch("ballbeam.communication.transport.serial.Serial", return_value=port), \
                 patch.object(main, "McuSerialClient", return_value=client), \
                 patch.object(main, "build_tracking_components", return_value=components), \
                 patch.object(main, "run_tracking_loop", side_effect=track), \
                 patch.object(client, "start_stream", wraps=client.start_stream) as start_stream, \
                 patch.object(client, "stop_stream", wraps=client.stop_stream) as stop_stream, \
                 patch.object(task_startup, "wait_for_operator_start") as operator, \
                 patch.object(task_startup.sys.stdin, "isatty", return_value=True), \
                 patch("builtins.input", return_value=""):
                self.assertEqual(main.run(args), 0)
                start_stream.assert_called_once_with(1.0 / args.ball_state_send_rate_hz)
                stop_stream.assert_called_once_with()
                operator.assert_called_once_with(1)
        commands = {frame[1] for frame in port.frames}
        self.assertEqual(commands, {6, 8 if tuning else 7})
        packets = [decode_pi_frame(frame) for frame in port.frames if frame[1] != 6]
        self.assertIn(0, {packet.task_id for packet in packets if packet.request_seq != 0})
        self.assertIn(1, {packet.task_id for packet in packets})
        self.assertFalse(port.is_open)

    def test_task_mode_startup_and_task_execution(self): self.run_mode(False)
    def test_tuning_mode_initialization_parameters_and_step(self): self.run_mode(True)
    def test_explicit_task_mode_and_task_id(self): self.run_mode(False, explicit=True)
    def test_explicit_debug_mode_and_task_id(self): self.run_mode(True, explicit=True)
