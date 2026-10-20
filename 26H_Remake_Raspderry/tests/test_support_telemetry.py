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
