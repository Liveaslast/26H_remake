"""Compile the real MCU protocol without HAL/RTOS and compare both wire ends."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ballbeam.communication.protocol import (
    MODE_REPLY_FRAME, RUN_TELEMETRY_FRAME, TUNING_TELEMETRY_FRAME,
    Mode, crc8, pack_run, pack_mode_request, pack_tuning, VelocityParameters,
)

class McuReceiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        root = Path(__file__).resolve().parents[2] / "26H_Remake_DJC"
        if not compiler or not root.exists():
            raise unittest.SkipTest("Host g++ and MCU source required")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        folder = Path(cls.directory.name)
        harness = folder / "protocol.cpp"
        harness.write_text(r'''
#include "PiProtocol.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
void Print(const uint8_t* data, unsigned size) {
    for (unsigned i = 0; i < size; ++i) std::printf("%02x", data[i]);
    std::puts("");
}
int main(int argc, char** argv) {
    if (argc < 2) return 2;
    std::string operation(argv[1]);
    if (operation == "direct") {
        std::string hex(argv[2]);
        PiProtocol::RxFrame frame;
        if (hex.size() / 2 > sizeof(frame.data)) return 2;
        frame.size = hex.size() / 2;
        for (unsigned i = 0; i < frame.size; ++i)
            frame.data[i] = std::stoul(hex.substr(i * 2, 2), nullptr, 16);
        PiProtocol::DecodedPiData input;
        input.mode_request.seq = 123;
        input.run_tuning.vision.x_cm = -456;
        if (PiProtocol::DecodeFrame(frame, input)) std::puts("accepted");
        else if (input.mode_request.seq == 123 && input.run_tuning.vision.x_cm == -456)
            std::puts("rejected unchanged");
        else std::puts("rejected modified");
        return 0;
    }
    if (operation == "reply") {
        PiProtocol::TxFrame frame;
        PiProtocol::PackModeReply({0x1234, COMM_MODE_TUNING, static_cast<uint8_t>(std::atoi(argv[2]))}, frame);
        Print(frame.data, frame.size);
        return 0;
    }
    if (operation == "telemetry" || operation == "limits" || operation == "extreme") {
        PiProtocol::TelemetrySample sample;
        sample.status = 31; sample.seq = 65535;
        sample.x_cm = -1.25f; sample.target_x_cm = 5;
        sample.vx_cm_s = -2.5f; sample.angle_deg = 21;
        sample.target_angle_deg = 22.25f; sample.stage = 10;
        sample.vision_seq = 65534; sample.vision_age_ms = 7;
        sample.control_x_cm = -1; sample.control_v_cm_s = -2;
        sample.target_v_cm_s = 3; sample.control_tick_ms = 1234;
        sample.stm32_time_ms = 1235; sample.request_seq = 99; sample.revision = 98;
        if (operation == "limits") {
            sample.x_cm = 500; sample.target_x_cm = -500;
            sample.vx_cm_s = std::numeric_limits<float>::quiet_NaN();
            sample.angle_deg = std::numeric_limits<float>::infinity();
            sample.vision_age_ms = 70000;
        }
        if (operation == "extreme") {
            sample.x_cm = std::numeric_limits<float>::max();
            sample.target_x_cm = -std::numeric_limits<float>::max();
        }
        PiProtocol::TxFrame frame;
        if (std::atoi(argv[2]) == COMM_MODE_RUN) PiProtocol::PackRunTelemetry(sample, frame);
        else PiProtocol::PackTuningTelemetry(sample, frame);
        Print(frame.data, frame.size);
        return 0;
    }
    PiProtocol::FrameExtractor decoder;
    for (int arg = 2; arg < argc; ++arg) {
        if (std::strcmp(argv[arg], "reset") == 0) { decoder.reset(); continue; }
        std::string hex(argv[arg]);
        for (unsigned i = 0; i < hex.size(); i += 2) {
            decoder.push(std::stoul(hex.substr(i, 2), nullptr, 16));
            PiProtocol::RxFrame frame;
            while (decoder.next(frame)) {
                if (operation == "receive") { Print(frame.data, frame.size); continue; }
                PiProtocol::DecodedPiData input;
                if (!PiProtocol::DecodeFrame(frame, input)) { std::puts("rejected"); continue; }
                if (input.frame_type == PiProtocol::FrameType::ModeRequest) {
                    std::printf("mode %u %u\n", input.mode_request.seq, input.mode_request.mode);
                } else {
                    const auto& data = input.run_tuning;
                    std::printf("data %u %u %.9g %.9g %lu %u %u %u %.7g %.7g %.7g %.7g %u %lu\n",
                        data.mode, data.vision.seq, data.vision.x_cm,
                        data.vision.vx_cm_s, static_cast<unsigned long>(data.vision.pi_time_ms),
                        data.vision.tracking_valid, data.task_id, data.request_seq,
                        data.kp, data.ki, data.kd, data.target_v_cm_s, data.revision,
                        static_cast<unsigned long>(data.vision.rx_tick_ms));
                }
            }
        }
    }
}
''', encoding="utf-8")
        cls.executable = folder / "protocol.exe"
        result = subprocess.run([
            compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
            "-I" + str(root / "Application/Communication/inc"), "-I" + str(root / "Application/BallBeam/inc"), str(harness), str(root / "Application/Communication/src/PiProtocol.cpp"),
            "-o", str(cls.executable),
        ], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def invoke(self, operation, *arguments):
        return subprocess.run([str(self.executable), operation, *map(str, arguments)],
                              capture_output=True, text=True, check=True).stdout.splitlines()

    def receive(self, chunks):
        return self.invoke("receive", *(chunk.hex() for chunk in chunks))

    def test_mixed_packets_in_one_dma_callback(self):
        packets = [pack_run(1, 0, 0, True, pi_time_ms=1),
                   pack_mode_request(2, Mode.RUN), pack_tuning(3, 0, 0, True, pi_time_ms=1)]
        self.assertEqual(self.receive([b"".join(packets)]), [p.hex() for p in packets])

    def test_every_byte_can_arrive_in_a_separate_callback(self):
        packet = pack_tuning(3, 0, 0, True, pi_time_ms=1)
        self.assertEqual(self.receive([bytes((b,)) for b in packet]), [packet.hex()])

    def test_corruption_resynchronizes_without_losing_following_short_frames(self):
        good = pack_mode_request(2, Mode.TUNING)
        bad = pack_tuning(3, 0, 0, True, pi_time_ms=1)
        bad = bad[:-1] + bytes((bad[-1] ^ 1,))
        self.assertEqual(self.receive([b"\xff\xa5\xff" + bad + good + good]),
                         [good.hex(), good.hex()])

    def test_partial_frame_survives_dma_callback_boundary(self):
        first = pack_run(1, 2, 0, True, pi_time_ms=1)
        second = pack_mode_request(2, Mode.RUN)
        self.assertEqual(self.receive([first[:8], first[8:] + second[:3], second[3:]]),
                         [first.hex(), second.hex()])

    def test_decoder_reset_drops_old_partial_frame(self):
        first = pack_tuning(1, 2, 0, True, pi_time_ms=1)
        good = pack_mode_request(3, Mode.RUN)
        self.assertEqual(self.invoke("receive", first[:10].hex(), "reset", good.hex()), [good.hex()])

    def test_decodes_scaled_parameters_and_signed_vision(self):
        packet = pack_tuning(65535, -1.25, -2.5, True, pi_time_ms=0xFFFFFFFF,
                             task_id=1, request_seq=123,
                             parameters=VelocityParameters(.5, .12, .02, -5), revision=456)
        fields = self.invoke("decode", packet.hex())[0].split()
        self.assertEqual(fields[:9], ["data", "2", "65535", "-1.25", "-2.5",
                                      "4294967295", "1", "1", "123"])
        for actual, expected in zip(fields[9:13], [.5, .12, .02, -5]):
            self.assertAlmostEqual(float(actual), expected, places=6)
        self.assertEqual(fields[13], "456")
        self.assertEqual(fields[14], "0")  # MCU time is supplied by communication, not protocol.

    def test_both_modes_decode_vision_into_physical_units(self):
        for pack in (pack_run, pack_tuning):
            for x, v in ((-11, -45), (11, 45), (0.01, -0.01), (0, 0)):
                with self.subTest(pack=pack.__name__, x=x):
                    packet = pack(37, x, v, True, pi_time_ms=123)
                    fields = self.invoke("decode", packet.hex())[0].split()
                    self.assertAlmostEqual(float(fields[3]), x, places=5)
                    self.assertAlmostEqual(float(fields[4]), v, places=5)
                    self.assertEqual(fields[2], "37")
                    self.assertEqual(fields[5:7], ["123", "1"])
                    self.assertEqual(fields[14], "0")

    def test_reserved_flags_are_rejected_after_crc(self):
        packet = bytearray(pack_run(1, 0, 0, True, pi_time_ms=1))
        packet[2] = 3
        packet[-1] = crc8(packet[:-1])
        self.assertEqual(self.invoke("decode", packet.hex()), ["rejected"])

    def test_mode_request_decode(self):
        self.assertEqual(self.invoke("decode", pack_mode_request(123, Mode.TUNING).hex()),
                         ["mode 123 2"])

    def test_direct_decode_checks_complete_frame_without_stream_decoder(self):
        packets = [pack_mode_request(7, Mode.RUN),
                   pack_run(1, -2, 3, True, pi_time_ms=5),
                   pack_tuning(2, -2, 3, False, pi_time_ms=5)]
        for packet in packets:
            with self.subTest(command=packet[1]):
                self.assertEqual(self.invoke("direct", packet.hex()), ["accepted"])
                corrupt = packet[:-1] + bytes((packet[-1] ^ 1,))
                bad_header = bytes((0x5A,)) + packet[1:]
                bad_command = packet[:1] + bytes((0xFF,)) + packet[2:]
                invalid = [b"", packet[:1], packet[:-1], corrupt, bad_header, bad_command]
                if len(packet) < 39:
                    invalid.append(packet + b"\x00")
                for malformed in invalid:
                    self.assertEqual(self.invoke("direct", malformed.hex()), ["rejected unchanged"])

    def test_direct_decode_rejects_reserved_flags_without_modifying_output(self):
        for packet in [pack_run(1, 0, 0, True, pi_time_ms=1),
                       pack_tuning(1, 0, 0, True, pi_time_ms=1)]:
            packet = bytearray(packet)
            packet[2] = 3
            packet[-1] = crc8(packet[:-1])
            self.assertEqual(self.invoke("direct", packet.hex()), ["rejected unchanged"])

    def test_very_large_finite_values_saturate_before_integer_conversion(self):
        for mode, layout in [(1, RUN_TELEMETRY_FRAME), (2, TUNING_TELEMETRY_FRAME)]:
            packet = bytes.fromhex(self.invoke("extreme", mode)[0])
            fields = layout.unpack(packet)
            self.assertEqual(fields[4:6], (32767, -32768))
            self.assertEqual(packet[-1], crc8(packet[:-1]))

    def test_mode_reply_both_results_match_pi_layout(self):
        for result in [0, 1]:
            packet = MODE_REPLY_FRAME.pack(0x5A, 0x86, 0x1234, 2, result, 0)
            packet = packet[:-1] + bytes((crc8(packet[:-1]),))
            self.assertEqual(self.invoke("reply", result), [packet.hex()])

    def test_telemetry_bytes_match_pi_for_both_modes_and_limits(self):
        for mode, layout, command in [(1, RUN_TELEMETRY_FRAME, 0x84),
                                      (2, TUNING_TELEMETRY_FRAME, 0x85)]:
            for limits in [False, True]:
                fields = [0x5A, command, 31, 65535, -125, 500, -250, 2100,
                          2225, 10, 65534, 7, -100, -200, 300, 1234, 1235, 99]
                if limits:
                    fields[4:8] = [32767, -32768, 0, 0]
                    fields[11] = 65535
                if mode == 2:
                    fields.append(98)
                packet = layout.pack(*fields, 0)
                packet = packet[:-1] + bytes((crc8(packet[:-1]),))
                self.assertEqual(self.invoke("limits" if limits else "telemetry", mode), [packet.hex()])
