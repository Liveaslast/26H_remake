"""Compile the actual MCU RX parser with host stubs, not the board firmware."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ballbeam.communication.protocol import pack_run, pack_mode_request, pack_tuning, Mode


class McuReceiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        root = Path(__file__).resolve().parents[2]
        source_path = root / "26H_Remake_DJC/APP/src/CommunicationTask.cpp"
        if not compiler or not source_path.exists():
            raise unittest.SkipTest("Host g++ and MCU source required")
        source = source_path.read_text(encoding="utf-8")
        structs = "\n".join(re.search(
            rf"struct __attribute__\(\(packed\)\) {name} \{{.*?\}};", source, re.S,
        ).group() for name in ("PiRxPackage", "TuningRxPackage", "ModeRequestPackage"))
        constants = "\n".join(re.findall(r"constexpr uint8_t k(?:PiRxSof|CmdRunState|CmdTuningState|CmdModeRequest) = .*?;", source))
        crc = source[source.index("static uint8_t ReverseBits"):source.index("void StartRaspberryUartReceive")]
        sizes = source[source.index("static uint16_t PiFrameSize"):source.index("static void DispatchPiFrameFromISR")]
        callback = source[source.index('extern "C" void HAL_UARTEx_RxEventCallback'):source.index('extern "C" void HAL_UART_TxCpltCallback')]
        harness = r'''
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <string>
using BaseType_t = int;
constexpr int pdFALSE = 0;
struct UART_HandleTypeDef {};
UART_HandleTypeDef uart;
auto *kRaspberryUart = &uart;
uint8_t raspberry_rx_buffer[128] = {};
uint8_t pi_frame_buffer[39] = {};
uint16_t pi_frame_bytes = 0;
#define portYIELD_FROM_ISR(x) ((void)(x))
void StartRaspberryUartReceive() {}
void DispatchPiFrameFromISR(uint16_t size, BaseType_t *) {
    for (uint16_t i = 0; i < size; ++i) std::printf("%02x", pi_frame_buffer[i]);
    std::puts("");
}
'''
        main = r'''
int main(int argc, char **argv) {
    for (int arg = 1; arg < argc; ++arg) {
        std::string hex(argv[arg]);
        unsigned count = hex.size() / 2;
        if (count > sizeof(raspberry_rx_buffer)) return 2;
        for (unsigned i = 0; i < count; ++i)
            raspberry_rx_buffer[i] = std::stoul(hex.substr(2*i, 2), nullptr, 16);
        HAL_UARTEx_RxEventCallback(&uart, count);
    }
}
'''
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        cpp = path / "receive.cpp"
        cls.executable = path / "receive.exe"
        cpp.write_text(harness + structs + constants + crc + sizes + callback + main, encoding="utf-8")
        result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", str(cpp),
                                 "-o", str(cls.executable)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def receive(self, chunks):
        result = subprocess.run([str(self.executable), *(chunk.hex() for chunk in chunks)],
                                capture_output=True, text=True, check=True)
        return result.stdout.splitlines()

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
