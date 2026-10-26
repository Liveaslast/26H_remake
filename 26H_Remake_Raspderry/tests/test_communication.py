"""Exercise actual serial worker and both operating modes without hardware."""

from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

from ballbeam.communication.protocol import (
    Mode, ModeReply, VelocityParameters, MODE_REQUEST_FRAME, MODE_REPLY_FRAME,
    PI_RUN_FRAME, PI_TUNING_FRAME, RUN_TELEMETRY_FRAME, TUNING_TELEMETRY_FRAME,
    pack_mode_request, pack_run, pack_tuning, crc8, decode_frame, decode_pi_frame,
)
from ballbeam.communication.protocol import FrameDecoder
from ballbeam.vision.angles import AngleHistory, interpolate_angle_samples
from ballbeam.app.task_startup import initialize_task_before_start, wait_for_first_angle
from fake_mcu import start_client, mode_reply, telemetry, wait_until, send_once


class CommunicationTests(unittest.TestCase):
    def test_six_frame_sizes_and_mode_wire_bytes(self):
        self.assertEqual([x.size for x in (MODE_REQUEST_FRAME, PI_RUN_FRAME, PI_TUNING_FRAME,
                                          MODE_REPLY_FRAME, RUN_TELEMETRY_FRAME, TUNING_TELEMETRY_FRAME)],
                         [6, 21, 39, 7, 37, 39])
        packet = pack_mode_request(0x1234, Mode.TUNING)
        self.assertEqual(packet[:-1], bytes.fromhex("a506341202"))
        self.assertEqual(packet[-1], crc8(packet[:-1]))
        self.assertEqual(decode_frame(mode_reply(0x1234, Mode.TUNING)),
                         ModeReply(Mode.TUNING, 0x1234, 0))

    def test_task_packet_units_and_request(self):
        frame = pack_run(65537, -1.25, 2.5, True,
                                pi_time_ms=(1 << 32) + 123, task_id=1, request_seq=7)
        packet = decode_pi_frame(frame)
        self.assertEqual((packet.seq, packet.pi_time_ms), (1, 123))
        self.assertEqual((packet.position_001cm, packet.velocity_001cms), (-125, 250))
        self.assertEqual((packet.task_id, packet.request_seq), (1, 7))

    def test_tuning_packet_contains_vision_and_parameters(self):
        frame = pack_tuning(1, 2, -3, True, pi_time_ms=4, task_id=2, request_seq=5,
                                  parameters=VelocityParameters(.5, .1, .02, -5), revision=6)
        fields = PI_TUNING_FRAME.unpack(frame)
        self.assertEqual(fields[4:9], (200, -300, 4, 2, 5))
        self.assertEqual(fields[9:14], (5000, 1000, 200, -500, 6))
        self.assertEqual(decode_pi_frame(frame).mode, Mode.TUNING)

    def test_parameter_validation_is_in_protocol(self):
        for values in ((5, 0, 0, 2), (.5, -1, 0, 2), (.5, 0, .3, 2), (.5, 0, 0, 0)):
            with self.assertRaises(ValueError):
                VelocityParameters(*values).scaled()

    def test_both_telemetries_preserve_control_columns(self):
        for mode in (Mode.RUN, Mode.TUNING):
            decoded = decode_frame(telemetry(mode=mode, request_seq=8, revision=9))
            self.assertEqual(decoded.mode, mode)
            self.assertEqual(decoded.actual_angle_deg, -12)
            self.assertEqual(decoded.sample.control_v, 1.9)
            self.assertEqual(decoded.sample.target_v, 5)
            for removed in ("bbp_deg", "trim_deg", "bbp", "bpush", "btrim", "bterm"):
                self.assertFalse(hasattr(decoded.sample, removed))
            self.assertEqual(decoded.request_seq, 8)
            self.assertEqual(decoded.revision, 9 if mode == Mode.TUNING else None)

    def test_bad_lengths_headers_and_crc_are_rejected(self):
        frame = telemetry()
        for bad in (b"", frame[:-1], b"\x00" + frame[1:], frame[:-1] + bytes((frame[-1] ^ 1,))):
            with self.assertRaises(ValueError):
                decode_frame(bad)

    def test_fragmented_mixed_receive_and_corruption_recovery(self):
        decoder = FrameDecoder()
        first, second = telemetry(), telemetry(mode=Mode.TUNING)
        reply = mode_reply(3)
        bad = first[:-1] + bytes((first[-1] ^ 1,))
        decoded = []
        data = b"\xff\x5a\xff" + bad + first + reply + second
        for offset in range(0, len(data), 3):
            decoded.extend(decoder.feed(data[offset:offset + 3]))
        self.assertEqual(len(decoded), 3)
        self.assertEqual(decoded[1], ModeReply(Mode.RUN, 3, 0))

    def test_no_data_is_sent_before_mode_confirmation(self):
        client, port = start_client(self, mode=None)
        client.start_stream(.005)
        client.publish_ball_state(1, 0, True)
        time.sleep(.025)
        self.assertEqual(port.frames, [])
        self.assertFalse(send_once(client, 1, 0, True))

    def test_mode_timeout_is_not_automatically_retried(self):
        client, port = start_client(self, mode=None)
        self.assertFalse(client.select_mode(Mode.RUN, timeout_seconds=.02))
        self.assertEqual(len(port.frames), 1)
        self.assertEqual(client.session.mode.current_mode, Mode.NONE)

    def test_mode_rejection_leaves_data_disabled(self):
        client, port = start_client(self, mode=None)
        port.on_write = lambda f: port.incoming.put(mode_reply(int.from_bytes(f[2:4], "little"), f[4], 1))
        self.assertFalse(client.select_mode(Mode.TUNING))
        self.assertFalse(send_once(client, 0, 0, False))

    def test_mode_write_failure_releases_caller_without_waiting_for_timeout(self):
        client, port = start_client(self, mode=None)
        with patch.object(port, "write", return_value=0):
            self.assertFalse(client.select_mode(Mode.RUN))
        self.assertEqual(client.session.mode.current_mode, Mode.NONE)
        self.assertIn("incomplete serial write", client.last_error)
        self.assertEqual(client.send_failures, 1)

    def test_mode_switch_discards_old_task_parameters_and_vision(self):
        client, port = start_client(self, Mode.TUNING)
        client.set_velocity_parameters(.8, .1, 0, -5)
        client.request_task(7)
        self.assertTrue(send_once(client, 3, 2, True))
        port.on_write = lambda frame: port.incoming.put(
            mode_reply(int.from_bytes(frame[2:4], "little"), frame[4])) if frame[1] == 6 else None
        self.assertTrue(client.select_mode(Mode.RUN))
        port.on_write = None
        client.start_stream(.005)
        wait_until(lambda: any(frame[1] == 7 for frame in port.frames))
        client.stop_stream()
        packet = decode_pi_frame(port.frames[-1])
        self.assertEqual((packet.task_id, packet.request_seq), (0, 0))
        self.assertFalse(packet.tracking_valid)
        self.assertEqual(packet.position_001cm, 0)
        self.assertEqual(client.session.stream.revision, 0)

    def test_modes_choose_only_their_own_data_packet(self):
        for mode, command in ((Mode.RUN, 7), (Mode.TUNING, 8)):
            client, port = start_client(self, mode)
            self.assertTrue(send_once(client, 1, 2, True))
            self.assertEqual(port.frames[-1][1], command)
            client.stop()

    def test_task_request_is_repeated_but_keeps_one_request_number(self):
        client, port = start_client(self)
        request = client.request_task(1)
        for _ in range(3):
            send_once(client, 0, 0, True)
        packets = [decode_pi_frame(f) for f in port.frames]
        self.assertEqual({(p.task_id, p.request_seq) for p in packets}, {(1, request)})
        self.assertEqual([p.seq for p in packets], [0, 1, 2])
        self.assertEqual(client.request_task(1), (request + 1) & 65535)

    def test_tuning_repeats_a_revision_without_changing_it(self):
        client, port = start_client(self, Mode.TUNING)
        revision = client.set_velocity_parameters(.5, .1, 0, -2)
        send_once(client, 0, 0, False)
        send_once(client, 1, 2, True)
        self.assertEqual({PI_TUNING_FRAME.unpack(f)[-2] for f in port.frames}, {revision})
        with self.assertRaises(ValueError):
            client.request_task(16)

    def test_transport_does_not_own_business_task_whitelist(self):
        client, port = start_client(self, Mode.TUNING)
        number = client.request_task(7)
        send_once(client, 0, 0, False)
        packet = decode_pi_frame(port.frames[-1])
        self.assertEqual((packet.task_id, packet.request_seq), (7, number))

    def test_request_zero_is_reserved_and_wrap_skips_it(self):
        client, port = start_client(self)
        send_once(client, 0, 0, False)
        self.assertEqual(decode_pi_frame(port.frames[-1]).request_seq, 0)
        self.assertEqual(client.request_task(0), 1)
        client.session._handlers["test_wrap"] = lambda _: setattr(client.session.stream, "_request_counter", 65535)
        client.session.call("test_wrap")
        self.assertEqual(client.request_task(0), 1)
        send_once(client, 0, 0, False)
        self.assertEqual((decode_pi_frame(port.frames[-1]).task_id,
                          decode_pi_frame(port.frames[-1]).request_seq), (0, 1))

    def test_wrong_mode_parameters_are_rejected(self):
        client, _ = start_client(self)
        with self.assertRaises(ValueError):
            client.set_velocity_parameters(.5, .1, 0, 2)

    def test_execution_results_come_from_telemetry_not_ack(self):
        client, port = start_client(self, Mode.TUNING)
        request = client.request_task(2)
        revision = client.set_velocity_parameters(.5, .1, 0, 2)
        self.assertIsNone(client.task_result(request))
        self.assertIsNone(client.parameters_result(revision))
        port.incoming.put(telemetry(status=24, mode=Mode.TUNING, request_seq=request, revision=revision))
        wait_until(lambda: client.task_result(request) is True)
        self.assertTrue(client.parameters_result(revision))
        self.assertIsNone(client.task_result(request + 1))

    def test_wrong_mode_telemetry_is_not_delivered(self):
        client, port = start_client(self)
        port.incoming.put(telemetry(mode=Mode.TUNING))
        time.sleep(.02)
        self.assertIsNone(client.latest_telemetry)

    def test_success_is_read_directly_from_status_bits(self):
        client, port = start_client(self, Mode.TUNING)
        port.incoming.put(telemetry(status=24, mode=Mode.TUNING, request_seq=3, revision=4))
        wait_until(lambda: client.task_result(3) is True)
        self.assertTrue(client.parameters_result(4))
        self.assertFalse(hasattr(client.latest_telemetry, "task_result"))
        self.assertFalse(hasattr(client.latest_telemetry, "config_result"))
        port.incoming.put(telemetry(status=0, seq=2, mode=Mode.TUNING, request_seq=3, revision=4))
        wait_until(lambda: client.task_result(3) is False)
        self.assertFalse(client.parameters_result(4))
        self.assertIsNone(client.task_result(5))

    def test_parameter_scaling_returns_a_tuple_not_bytes(self):
        values = VelocityParameters(.8, .1, 0, 5).scaled()
        self.assertEqual(values, (8000, 1000, 0, 500))
        self.assertIsInstance(values, tuple)

    def test_one_communication_thread_owns_serial_io(self):
        create = threading.Thread
        with patch("ballbeam.communication.session.threading.Thread", wraps=create) as factory:
            client, port = start_client(self)
        self.assertEqual(factory.call_count, 1)
        port.incoming.put(telemetry())
        send_once(client, 0, 0, True)
        wait_until(lambda: client.latest_telemetry is not None)
        self.assertEqual(set(port.writers), {"McuCommunication"})
        self.assertEqual(set(port.readers), {"McuCommunication"})

    def test_stream_runs_without_rx_and_stops(self):
        client, port = start_client(self)
        client.start_stream(.005)
        client.publish_ball_state(3, 2, True)
        wait_until(lambda: len(port.frames) >= 4)
        client.stop_stream()
        count = len(port.frames)
        time.sleep(.02)
        self.assertEqual(len(port.frames), count)

    def test_stream_does_not_keep_old_vision_valid(self):
        client, port = start_client(self)
        client.start_stream(.005)
        client.publish_ball_state(3, 2, True)
        wait_until(lambda: any(f[2] & 1 for f in port.frames))
        wait_until(lambda: len(port.frames) > 4 and not (port.frames[-1][2] & 1))
        self.assertEqual(decode_pi_frame(port.frames[-1]).position_001cm, 300)

    def test_failed_write_does_not_advance_sequence(self):
        client, port = start_client(self)
        with patch.object(port, "write", return_value=0):
            self.assertFalse(send_once(client, 1, 0, True))
        self.assertTrue(send_once(client, 2, 0, True))
        self.assertEqual(decode_pi_frame(port.frames[-1]).seq, 0)

    def test_delayed_image_result_does_not_refresh_vision_validity(self):
        client, port = start_client(self)
        client.start_stream(.005)
        client.publish_ball_state(3, 2, True, measured_at=time.monotonic() - .5)
        wait_until(lambda: any(decode_pi_frame(f).position_001cm == 300 for f in port.frames))
        client.stop_stream()
        self.assertFalse(any(f[2] & 1 for f in port.frames))

    def test_fresh_image_timestamp_is_preserved_for_periodic_sender(self):
        client, port = start_client(self)
        measured_at = time.monotonic()
        client.publish_ball_state(3, 2, True, measured_at=measured_at)
        client.start_stream(.005)
        wait_until(lambda: client.visual_state_sent)
        self.assertEqual(client.session.stream.latest_ball[3], measured_at)

    def test_nonfinite_image_timestamp_is_never_marked_valid(self):
        client, port = start_client(self)
        client.publish_ball_state(3, 2, True, measured_at=float("nan"))
        client.start_stream(.005)
        wait_until(lambda: any(decode_pi_frame(f).position_001cm == 300 for f in port.frames))
        client.stop_stream()
        self.assertFalse(any(f[2] & 1 for f in port.frames))

    def test_log_failure_does_not_break_stream(self):
        client, port = start_client(self)
        client.record_sent_frame = MagicMock(side_effect=OSError("log unavailable"))
        self.assertTrue(send_once(client, 1, 0, True))
        self.assertIsNone(client.record_sent_frame)
        self.assertTrue(send_once(client, 2, 0, True))

    def test_sent_frame_callback_receives_decoded_packet(self):
        client, _ = start_client(self)
        client.record_sent_frame = MagicMock()
        self.assertTrue(send_once(client, 1.25, -2, True))
        packet, sent_at = client.record_sent_frame.call_args.args
        self.assertTrue(packet.tracking_valid)
        self.assertEqual(packet.position_001cm, 125)
        self.assertEqual(packet.velocity_001cms, -200)
        self.assertIsInstance(sent_at, float)
        self.assertNotIn("ball", client.session._handlers)
        self.assertTrue(send_once(client, 0, 0, False))
        self.assertFalse(client.visual_state_sent)

    def test_shutdown_releases_pending_mode_selection(self):
        client, port = start_client(self, mode=None)
        results = []
        caller = threading.Thread(target=lambda: results.append(client.select_mode(Mode.RUN)))
        caller.start()
        wait_until(lambda: len(port.frames) == 1)
        client.stop()
        caller.join(timeout=1)
        self.assertEqual(results, [False])
        self.assertFalse(port.is_open)

    def test_startup_initialization_uses_task_packet_and_telemetry(self):
        client, port = start_client(self)
        def respond(frame):
            packet = decode_pi_frame(frame)
            port.incoming.put(telemetry(status=8, request_seq=packet.request_seq))
        port.on_write = respond
        client.start_stream(.005)
        self.assertTrue(initialize_task_before_start(client))
        self.assertTrue(all(frame[1] == 7 for frame in port.frames))
        self.assertEqual(decode_pi_frame(port.frames[-1]).task_id, 0)
        self.assertNotEqual(decode_pi_frame(port.frames[-1]).request_seq, 0)

    def test_angle_cache_is_independent_and_receives_mode_telemetry(self):
        client, port = start_client(self)
        angles = AngleHistory()
        client.record_actual_angle = angles.record
        port.incoming.put(telemetry(angle=2100))
        self.assertEqual(wait_for_first_angle(client, angles, 1).angle_deg, 21)
        self.assertFalse(hasattr(angles, "client"))
        reading = interpolate_angle_samples(((1.0, 12.0), (1.1, 22.0)), 1.05, .06)
        self.assertAlmostEqual(reading.angle_deg, 17)

    def test_angle_readiness_also_delivers_control_sample_without_sending(self):
        client, port = start_client(self)
        angles = AngleHistory()
        samples = []
        client.record_actual_angle = angles.record
        client.record_control_sample = samples.append
        port.incoming.put(telemetry())
        self.assertIsNotNone(wait_for_first_angle(client, angles, 1))
        wait_until(lambda: len(samples) == 1)
        self.assertEqual(port.frames, [])
