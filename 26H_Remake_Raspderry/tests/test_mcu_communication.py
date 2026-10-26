"""验证真实MCU通信协调代码；队列和DMA使用主机替身，不连接设备。"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ballbeam.communication.protocol import (
    Mode, VelocityParameters, pack_mode_request, pack_run, pack_tuning,
)

class McuCommunicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        root = Path(__file__).resolve().parents[2] / "26H_Remake_DJC"
        if not compiler or not root.exists():
            raise unittest.SkipTest("Host g++ and MCU source required")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        folder = Path(cls.directory.name)
        (folder / "cmsis_os.h").write_text(r'''
#pragma once
#include <cstdint>
#include <cstring>
#include <deque>
#include <vector>
struct Queue { unsigned capacity, item_size; std::deque<std::vector<uint8_t>> items; };
using osMessageQueueId_t = Queue*;
constexpr int osOK = 0;
Queue* osMessageQueueNew(unsigned, unsigned, void*);
inline int osMessageQueuePut(Queue* q, const void* data, unsigned, unsigned) {
    if (!q || q->items.size() == q->capacity) return -1;
    auto bytes = static_cast<const uint8_t*>(data);
    q->items.emplace_back(bytes, bytes + q->item_size); return osOK;
}
inline int osMessageQueueGet(Queue* q, void* data, void*, unsigned) {
    if (!q || q->items.empty()) return -1;
    std::memcpy(data, q->items.front().data(), q->item_size); q->items.pop_front(); return osOK;
}
void osDelay(unsigned);
''')
        (folder / "FreeRTOS.h").write_text(
            "#pragma once\nusing BaseType_t = int;\nconstexpr int pdFALSE=0;\n")
        (folder / "task.h").write_text(
            "#pragma once\n#include <cassert>\ninline int critical_depth = 0;\n"
            "inline void EnterCritical() { assert(critical_depth == 0); ++critical_depth; }\n"
            "inline void ExitCritical() { assert(critical_depth == 1); --critical_depth; }\n"
            "#define taskENTER_CRITICAL() EnterCritical()\n"
            "#define taskEXIT_CRITICAL() ExitCritical()\n#define portYIELD_FROM_ISR(x) ((void)(x))\n")
        (folder / "queue.h").write_text(
            '#pragma once\n#include "cmsis_os.h"\nusing QueueHandle_t = Queue*;\n'
            'inline int xQueueSendToBackFromISR(Queue* q, const void* data, int*) '
            '{ return osMessageQueuePut(q, data, 0, 0); }\n')
        (folder / "usart.h").write_text(r'''
#pragma once
#include <cstdint>
struct UART_HandleTypeDef { void* hdmarx = nullptr; };
extern UART_HandleTypeDef huart1;
constexpr int HAL_OK = 0, DMA_IT_HT = 0;
#define __HAL_DMA_DISABLE_IT(handle, flag) ((void)(handle), (void)(flag))
#define __HAL_UNLOCK(handle) ((void)(handle))
uint32_t HAL_GetTick();
int HAL_UARTEx_ReceiveToIdle_DMA(UART_HandleTypeDef*, uint8_t*, unsigned);
int HAL_UART_Transmit_DMA(UART_HandleTypeDef*, uint8_t*, unsigned);
''')
        (folder / "Serial.h").write_text(
            '#pragma once\n#include "usart.h"\ninline void Serial_OnTxCplt(UART_HandleTypeDef*) {}\n'
            'inline void Serial_OnError(UART_HandleTypeDef*) {}\n')
        (folder / "check.cpp").write_text(r'''
#include "CommunicationTask.cpp"
#include <cassert>
#include <cstdlib>
#include <string>
#include <memory>
UART_HandleTypeDef huart1;
unsigned now_ms = 100, delays = 0;
int dma_result = HAL_OK;
bool test_loop = false;
PiProtocol::RxFrame incoming;
std::vector<std::unique_ptr<Queue>> queues;
Queue* osMessageQueueNew(unsigned capacity, unsigned item_size, void*) {
    queues.emplace_back(new Queue{capacity, item_size, {}});
    return queues.back().get();
}
uint32_t HAL_GetTick() { return now_ms; }
int HAL_UARTEx_ReceiveToIdle_DMA(UART_HandleTypeDef*, uint8_t*, unsigned) {
    if (test_loop) assert(osMessageQueuePut(rx_queue, &incoming, 0, 0) == osOK);
    return HAL_OK;
}
int HAL_UART_Transmit_DMA(UART_HandleTypeDef*, uint8_t*, unsigned) {
    assert(critical_depth == 0);
    return dma_result;
}
PiProtocol::TelemetrySample CollectAppTelemetry(uint32_t now) {
    PiProtocol::TelemetrySample sample;
    sample.x_cm = 1.25f; sample.status = 3; sample.stm32_time_ms = now;
    return sample;
}
struct StopLoop {};
void osDelay(unsigned) {
    ++delays;
    PiModeRequest_t request;
    if (delays == 1) {
        assert(rx_queue->items.empty() && queues.size() == 1);
        assert(Communication_ReadModeRequest(&request) && request.seq == 41);
        Communication_SaveModeResult(&request, 0);
    } else if (delays == 2) {
        assert(mode_exchange.stage == ModeExchange::Stage::Idle);
        assert(tx_busy && tx_frame.data[2] == 41);
        HAL_UART_TxCpltCallback(&huart1);
    } else if (delays == 3) {
        assert(Communication_ReadModeRequest(&request) && request.seq == 42);
        Communication_SaveModeResult(&request, 0);
    } else {
        assert(tx_busy && tx_frame.data[2] == 42 && mode_generation == 2);
        throw StopLoop{};
    }
}
void SelectMode(uint8_t mode, uint16_t seq = 1, uint8_t result = 0) {
    mode_exchange.request = {seq, mode};
    mode_exchange.stage = ModeExchange::Stage::Requested;
    auto request = mode_exchange.request;
    Communication_SaveModeResult(&request, result);
}
int main(int argc, char** argv) {
    if (argc != 3) return 2;
    std::string hex(argv[2]); incoming.size = hex.size() / 2;
    for (unsigned i = 0; i < incoming.size; ++i)
        incoming.data[i] = std::stoul(hex.substr(i*2, 2), nullptr, 16);
    int scenario = std::atoi(argv[1]);
    if (scenario == 1) {
        test_loop = true;
        mode_exchange.request = {41, COMM_MODE_RUN};
        mode_exchange.stage = ModeExchange::Stage::Requested;
        try { StartCommunicationTask(nullptr); } catch (StopLoop&) {}
        assert(delays == 4);
    } else if (scenario == 2) {
        SelectMode(COMM_MODE_RUN, 10);
        PiModeRequest_t old{10, COMM_MODE_RUN};
        Communication_SaveModeResult(&old, 0);
        assert(mode_generation == 1 && !ProcessInput(incoming));
        tx_busy = true; SendModeReply();
        assert(mode_exchange.stage == ModeExchange::Stage::ReplyReady);
        tx_busy = false; dma_result = -1; SendModeReply();
        assert(!tx_busy && mode_exchange.stage == ModeExchange::Stage::ReplyReady);
        dma_result = HAL_OK; SendModeReply();
        assert(tx_busy && tx_frame.data[2] == 10);
        assert(ProcessInput(incoming));
        PiModeRequest_t next;
        assert(Communication_ReadModeRequest(&next) && next.seq == 42);
        auto wrong = next; wrong.seq++;
        Communication_SaveModeResult(&wrong, 0);
        assert(mode_exchange.stage == ModeExchange::Stage::Requested && mode_generation == 1);
        Communication_SaveModeResult(&next, 0);
        SendModeReply();
        assert(tx_frame.data[2] == 10);
        HAL_UART_TxCpltCallback(&huart1); SendModeReply();
        assert(tx_busy && tx_frame.data[2] == 42 && mode_generation == 2);
    } else if (scenario == 3) {
        VisionData_t vision_data{};
        assert(!Communication_ReadLatestVisionData(&vision_data, 0));
        SelectMode(COMM_MODE_RUN);
        assert(ProcessInput(incoming));
        assert(Communication_ReadLatestVisionData(&vision_data, 0) && !vision_data.tracking_valid);
        assert(!(CollectTelemetry().status & 4));
        execution_request.request_seq = 7; execution_request.revision = 8;
        Communication_SaveExecutionResult(PI_RESULT_TASK, 7, false);
        assert(handled_task_request_seq == 7 && !(CollectTelemetry().status & 8));
        Communication_SaveExecutionResult(PI_RESULT_TASK, 7, true);
        Communication_SaveExecutionResult(PI_RESULT_PARAMETERS, 8, true);
        auto sample = CollectTelemetry();
        assert(sample.x_cm == 1.25f && sample.status == 27 && sample.seq == 2);
        assert(sample.request_seq == 7 && sample.revision == 8 && sample.stm32_time_ms == now_ms);
        execution_request.request_seq = 9; execution_request.revision = 10;
        sample = CollectTelemetry();
        assert(sample.status == 3 && sample.request_seq == 7 && sample.revision == 8);
        SelectMode(COMM_MODE_TUNING);
        assert(!has_vision_data && !has_execution_request && !task_request_succeeded);
        assert(handled_task_request_seq == 7);
    } else if (scenario == 4) {
        SelectMode(COMM_MODE_TUNING, 10, 1);
        assert(current_mode == COMM_MODE_NONE && mode_generation == 0);
        SendModeReply();
        assert(tx_frame.size == 7 && tx_frame.data[2] == 10 && tx_frame.data[4] == 2);
        assert(tx_frame.data[5] == 1);
    } else if (scenario == 5) {
        SelectMode(COMM_MODE_RUN);
        assert(ProcessInput(incoming));
        VisionData_t vision{};
        assert(Communication_ReadLatestVisionData(&vision, 0));
        assert(vision.x_cm == -11.f && vision.vx_cm_s == -2.5f);
        assert(vision.seq == 37 && vision.pi_time_ms == 123 && vision.rx_tick_ms == now_ms);
        now_ms += 101;
        assert(!Communication_ReadLatestVisionData(&vision, 100));
        assert(Communication_ReadLatestVisionData(&vision, 0));
    } else if (scenario == 6) {
        SelectMode(COMM_MODE_RUN);
        assert(ProcessInput(incoming));
        assert(has_vision_data && has_execution_request);
        VisionData_t vision{};
        assert(Communication_ReadLatestVisionData(&vision, 0));
        assert(vision.x_cm > 11.f && vision.tracking_valid && vision.seq == 37);
        assert(vision.pi_time_ms == 123 && vision.rx_tick_ms == now_ms);
        assert(CollectTelemetry().status & 4); // Pi reported tracking, not estimator acceptance.
        PiProtocol::DecodedPiData decoded;
        assert(PiProtocol::DecodeFrame(incoming, decoded));
        decoded.run_tuning.vision.tracking_valid = 0;
        taskENTER_CRITICAL();
        SaveVisionData(decoded.run_tuning.vision);
        taskEXIT_CRITICAL();
        assert(has_vision_data && !latest_vision_data.tracking_valid);
        SelectMode(COMM_MODE_TUNING);
        assert(ProcessInput(incoming));
        assert(!has_vision_data && !has_execution_request);
    } else if (scenario == 7) {
        SelectMode(COMM_MODE_RUN);
        assert(ProcessInput(incoming)); // TUNING input cannot overwrite RUN inputs.
        assert(!has_vision_data && !has_execution_request);
        SelectMode(COMM_MODE_TUNING);
        assert(ProcessInput(incoming));
        VisionData_t vision{};
        PiExecutionRequest_t request{};
        assert(Communication_ReadLatestVisionData(&vision, 100));
        assert(Communication_ReadExecutionRequest(&request));
        assert(vision.x_cm == 2.f && vision.vx_cm_s == -1.f && vision.seq == 37);
        assert(vision.pi_time_ms == 123 && vision.rx_tick_ms == now_ms);
        assert(request.mode == COMM_MODE_TUNING && request.mode_generation == 2);
        assert(request.task_id == 1 && request.request_seq == 7 && request.revision == 8);
        assert(request.kp == 1.f && request.ki == 2.f && request.kd == 0.125f);
        assert(request.target_v_cm_s == 3.f && !tx_busy); // Saving is not sending/executing.
    } else if (scenario == 8) {
        uint32_t last_tx_ms = now_ms;
        now_ms = 120;
        SendTelemetryWhenDue(last_tx_ms);
        assert(!tx_busy && telemetry_frame_seq == 0); // No selected mode, no telemetry.
        SelectMode(COMM_MODE_RUN);
        SendModeReply();
        now_ms = 139;
        SendTelemetryWhenDue(last_tx_ms);
        assert(tx_frame.data[1] == 0x86 && telemetry_frame_seq == 0);
        now_ms = 140;
        SendTelemetryWhenDue(last_tx_ms);
        assert(tx_frame.data[1] == 0x86 && telemetry_frame_seq == 0); // DMA still owns ACK.
        HAL_UART_TxCpltCallback(&huart1);
        now_ms = 160;
        SendTelemetryWhenDue(last_tx_ms);
        assert(tx_busy && tx_frame.data[1] == 0x84 && tx_frame.size == 37);
        assert(telemetry_frame_seq == 1);
        HAL_UART_TxCpltCallback(&huart1);
        SelectMode(COMM_MODE_TUNING);
        SendModeReply();
        HAL_UART_TxCpltCallback(&huart1);
        now_ms = 164;
        SendTelemetryWhenDue(last_tx_ms);
        assert(!tx_busy && telemetry_frame_seq == 1);
        now_ms = 165;
        SendTelemetryWhenDue(last_tx_ms);
        assert(!tx_busy && telemetry_frame_seq == 1); // TUNING also waits 20ms, not 5ms.
        now_ms = 179;
        SendTelemetryWhenDue(last_tx_ms);
        assert(!tx_busy && telemetry_frame_seq == 1);
        now_ms = 180;
        SendTelemetryWhenDue(last_tx_ms);
        assert(tx_busy && tx_frame.data[1] == 0x85 && tx_frame.size == 39);
        assert(telemetry_frame_seq == 2);
    } else return 2;
    assert(critical_depth == 0);
}
''')
        cls.executable = folder / "check.exe"
        result = subprocess.run([
            compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
            "-I" + str(folder), "-I" + str(root / "APP/inc"), "-I" + str(root / "Application/Communication/inc"), "-I" + str(root / "Application/BallBeam/inc"), "-I" + str(root / "APP/src"),
            str(folder / "check.cpp"), str(root / "Application/Communication/src/PiProtocol.cpp"),
            "-o", str(cls.executable),
        ], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def scenario(self, number, packet):
        result = subprocess.run([str(self.executable), str(number), packet.hex()],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mode_slot_backpressure_retains_frame_in_actual_task_loop(self):
        self.scenario(1, pack_mode_request(42, Mode.RUN))

    def test_mode_slot_and_failed_dma_preserve_reply_order(self):
        self.scenario(2, pack_mode_request(42, Mode.RUN))

    def test_snapshot_presence_result_kind_and_mode_generation_are_distinct(self):
        self.scenario(3, pack_run(1, 0, 0, False, pi_time_ms=1))

    def test_failed_mode_completion_sends_failure_without_switching(self):
        self.scenario(4, pack_mode_request(42, Mode.RUN))

    def test_physical_vision_values_and_receive_time_reach_app(self):
        self.scenario(5, pack_run(37, -11, -2.5, True, pi_time_ms=123))

    def test_communication_saves_out_of_range_and_invalid_vision_without_filtering(self):
        self.scenario(6, pack_run(37, 11.01, 0, True, pi_time_ms=123))

    def test_tuning_frame_saves_vision_and_parameters_only_in_selected_mode(self):
        self.scenario(7, pack_tuning(
            37, 2, -1, True, pi_time_ms=123, task_id=1, request_seq=7,
            parameters=VelocityParameters(1, 2, 0.125, 3), revision=8,
        ))

    def test_periodic_telemetry_uses_selected_mode_without_overwriting_busy_dma(self):
        self.scenario(8, pack_mode_request(42, Mode.RUN))
