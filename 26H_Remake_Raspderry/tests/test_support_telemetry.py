"""The separate calibration tools must understand the new wire format too."""

from pathlib import Path
import sys
import unittest

from ballbeam.communication.protocol import Mode, decode_pi_frame, pack_mode_request
from fake_mcu import FakeSerial, mode_reply, telemetry


class SupportTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2] / "26H_Remake_Support"
        if not root.exists():
            raise unittest.SkipTest("Separate Support project not deployed")
        sys.path.insert(0, str(root))
        cls.addClassCleanup(lambda: sys.path.remove(str(root)))
        from Vision.IO.camera_telemetry import _HtaskSerialClient, _pack_ball_state
        cls.Client = _HtaskSerialClient
        cls.pack = staticmethod(_pack_ball_state)

    def test_support_visual_packet_matches_formal_layout(self):
        decoded = decode_pi_frame(self.pack(1, 2, -3, False))
        self.assertEqual((decoded.task_id, decoded.request_seq), (0, 0))
        self.assertEqual(decoded.position_001cm, 200)

    def test_preparation_tool_confirms_mode_without_motion_request(self):
        client = self.Client("unused", 115200, read_timeout_seconds=.001, write_timeout_seconds=.01)
        port = FakeSerial()
        client._serial = port
        port.on_write = lambda _frame: port.incoming.put(mode_reply(0) + telemetry(angle=2100))
        client._select_task_mode()
        self.assertEqual(port.frames, [pack_mode_request(0, Mode.RUN)])
        self.assertEqual(client.latest_actual_angle.actual_angle_deg, 21)

    def test_support_extracts_both_shortened_telemetry_frames_from_fragments(self):
        client = self.Client("unused", 115200, read_timeout_seconds=.001, write_timeout_seconds=.01)
        client._mode_ready = True
        angles = []
        client.on_actual_angle = lambda value: angles.append(value.actual_angle_deg)
        data = telemetry(angle=2100) + telemetry(mode=Mode.TUNING, angle=-1200)
        for offset in range(0, len(data), 3):
            client._rx_buffer.extend(data[offset:offset + 3])
            client._parse_available()
        self.assertEqual(angles, [21, -12])
        self.assertEqual(client._rx_buffer, b"")

    def test_debug_collectors_accept_only_current_seven_column_control_rows(self):
        from Diagnostics.APP.capture_mcu_csv import FIRMWARE_FIELDS, parse_firmware_sample
        from Diagnostics.Core.ballbeam_capture import CHANNELS, parse_line
        line = "-125,500,-250,2100,2225,2,7"
        self.assertEqual(len(FIRMWARE_FIELDS), 7)
        self.assertEqual(parse_firmware_sample(line), [-1.25, 5, -2.5, 21, 22.25, 2, 7])
        row = parse_line(line)
        self.assertEqual(list(row), CHANNELS)
        self.assertEqual(row["angle"], 21)
        self.assertEqual(row["seq_stage"], 2)
        self.assertEqual(row["age_ms"], 7)
        legacy = "0,0,0,0,0,0,0,0,0,0,0,0,0"
        self.assertIsNone(parse_firmware_sample(legacy))
        self.assertIsNone(parse_line(legacy))

    def test_task_analysis_uses_current_columns_without_old_action_flags(self):
        import contextlib
        import io
        from Diagnostics.APP.analyze_task1 import summarize_leg
        rows = [dict(t_s=i * .1, phase="plus5", ab_x=float(i), target_x=5.0,
                     ab_v=1.0, angle=21.0, target_angle=22.0, seq_stage=1, age_ms=5)
                for i in range(6)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            summarize_leg("plus5", rows, 5.0, 1)
        self.assertIn("target_cross", output.getvalue())
        self.assertNotIn("bbp", output.getvalue())
        self.assertNotIn("trim_deg", output.getvalue())
