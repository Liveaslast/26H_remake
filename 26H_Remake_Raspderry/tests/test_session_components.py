"""Communication components can be exercised without a worker or serial device."""

import ast
from concurrent.futures import Future
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from ballbeam.communication.protocol import Mode, ModeReply, VelocityParameters, decode_pi_frame
from ballbeam.communication import session
from ballbeam.communication.session import ModeRequest, DataStream, FrameSender


class SessionComponentTests(unittest.TestCase):
    def setUp(self):
        self.mode = ModeRequest()
        self.mode.current_mode = Mode.RUN
        self.stream = DataStream(self.mode)
        self.transport = Mock()
        self.transport.write.return_value = True
        self.record_sent = Mock()
        self.sender = FrameSender(self.transport, self.record_sent)

    def test_request_changes_fields_without_serial_io(self):
        number = self.stream.request_task(7)
        fields = self.stream.snapshot(10)
        self.assertEqual((fields["task_id"], fields["request_seq"]), (7, number))
        self.transport.write.assert_not_called()

    def test_parameters_select_owner_without_reusing_task_request_number(self):
        self.mode.current_mode = Mode.TUNING
        initialize_request = self.stream.request_task(0)
        revision = self.stream.set_parameters((1, VelocityParameters(.8, .1, 0, -5)))
        fields = self.stream.snapshot(10)
        self.assertEqual((fields["task_id"], fields["request_seq"], fields["revision"]), (1, 0, revision))
        self.assertEqual(self.stream.request_task(1), initialize_request + 1)

    def test_parameter_owner_must_be_a_valid_wire_task_id(self):
        self.mode.current_mode = Mode.TUNING
        with self.assertRaises(ValueError):
            self.stream.set_parameters((16, VelocityParameters()))
        self.assertEqual((self.stream.task_id, self.stream.revision), (0, 0))

    def test_latest_sample_replaces_old_sample_and_obeys_period(self):
        with patch("ballbeam.communication.session.time.monotonic", return_value=10):
            self.sender.set_period(.02)
            self.stream.publish_vision(1, 0, True, measured_at=10)
            self.stream.publish_vision(2, 0, True, measured_at=10)
            self.sender.send_due(Mode.RUN, self.stream, 10)
            self.sender.send_due(Mode.RUN, self.stream, 10.01)
        self.transport.write.assert_called_once()
        packet = decode_pi_frame(self.transport.write.call_args.args[0])
        self.assertEqual(packet.position_001cm, 200)
        self.assertTrue(packet.tracking_valid)

    def test_stale_sample_retains_position_but_clears_valid_flag(self):
        self.sender.period = .02
        self.stream.publish_vision(2, 0, True, measured_at=9)
        with patch("ballbeam.communication.session.time.monotonic", return_value=10):
            self.sender.send_due(Mode.RUN, self.stream, 10)
        packet = decode_pi_frame(self.transport.write.call_args.args[0])
        self.assertFalse(packet.tracking_valid)
        self.assertEqual(packet.position_001cm, 200)

    def test_failed_write_keeps_sequence_and_does_not_notify(self):
        self.transport.write.return_value = False
        self.assertFalse(self.sender.send_data(Mode.RUN, self.stream))
        self.assertEqual(self.stream.packet_seq, 0)
        self.assertEqual(self.sender.send_failures, 1)
        self.record_sent.assert_not_called()

    def test_unconfirmed_mode_disables_sender_and_task_requests(self):
        self.mode.current_mode = Mode.NONE
        self.assertFalse(self.sender.send_data(Mode.NONE, self.stream))
        with self.assertRaises(ValueError):
            self.stream.request_task(1)
        self.transport.write.assert_not_called()

    def test_mode_change_clears_request_and_vision_but_keeps_packet_counter(self):
        self.mode.current_mode = Mode.TUNING
        self.stream.request_task(1)
        self.stream.set_parameters((1, VelocityParameters(.8, .1, 0, -5)))
        self.stream.publish_vision(1, 0, True, measured_at=10)
        self.stream.mark_sent()
        self.stream.reset()
        self.assertEqual(self.stream.request_seq, 0)
        self.assertEqual(self.stream.revision, 0)
        self.assertEqual(self.stream.parameters, VelocityParameters())
        self.assertEqual(self.stream.packet_seq, 1)
        self.assertIsNone(self.stream.latest_ball)
        self.assertTrue(self.stream.updates.empty())

    def test_mode_and_data_frames_share_one_write_interface(self):
        reply = Future()
        self.mode.begin(Mode.TUNING, reply, 1)
        with patch.object(self.sender, "_write", wraps=self.sender._write) as write:
            self.assertTrue(self.sender.send_mode(self.mode))
            self.assertFalse(reply.done())
            self.mode.receive(ModeReply(Mode.TUNING, self.mode.seq, 0))
            self.stream.set_parameters((1, VelocityParameters(.8, .1, 0, -5)))
            self.assertTrue(self.sender.send_data(Mode.TUNING, self.stream))
        self.assertEqual([call.args[0][1] for call in write.call_args_list], [0x06, 0x08])
        self.record_sent.assert_called_once()

    def test_only_sender_writes_serial_and_uses_protocol_encoders(self):
        tree = ast.parse(Path(session.__file__).read_text(encoding="utf-8"))
        owners = []
        for component in tree.body:
            if not isinstance(component, ast.ClassDef):
                continue
            for node in ast.walk(component):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func
                if isinstance(name, ast.Attribute) and name.attr == "write":
                    owners.append(component.name)
                if isinstance(name, ast.Name) and name.id in {
                    "pack_mode_request", "pack_run", "pack_tuning",
                }:
                    self.assertEqual(component.name, "FrameSender")
        self.assertEqual(owners, ["FrameSender"])

    def test_mode_request_allocates_sequence_and_rejects_old_reply(self):
        first, second = Future(), Future()
        self.mode.begin(Mode.RUN, first, 1)
        old_seq = self.mode.seq
        self.mode.check_timeout(self.mode.deadline)
        self.mode.begin(Mode.RUN, second, 1)
        self.assertEqual(self.mode.seq, old_seq + 1)
        self.mode.receive(ModeReply(Mode.RUN, old_seq, 0))
        self.assertFalse(second.done())
        self.mode.receive(ModeReply(Mode.RUN, self.mode.seq, 0))
        self.assertTrue(second.result())

    def test_mode_sequence_wraps_at_16_bits(self):
        self.mode._next_seq = 65535
        self.mode.begin(Mode.RUN, Future(), 1)
        self.assertEqual(self.mode.seq, 65535)
        self.mode.fail("test")
        self.mode.begin(Mode.RUN, Future(), 1)
        self.assertEqual(self.mode.seq, 0)

    def test_sent_callback_failure_does_not_undo_serial_write(self):
        self.record_sent.side_effect = OSError("recording failed")
        self.assertTrue(self.sender.send_data(Mode.RUN, self.stream))
        self.assertEqual(self.stream.packet_seq, 1)
        self.assertEqual(self.sender.send_failures, 0)
        self.assertEqual(self.sender.last_error, "recording failed")

    def test_mode_write_failure_is_recorded_without_data_callback(self):
        self.mode.begin(Mode.RUN, Future(), 1)
        self.transport.write.return_value = False
        self.transport.last_error = "disconnected"
        self.assertFalse(self.sender.send_mode(self.mode))
        self.assertEqual(self.sender.last_error, "disconnected")
        self.assertEqual(self.sender.send_failures, 1)
        self.record_sent.assert_not_called()
