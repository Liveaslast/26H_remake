#include "CommunicationTask.h"

#include <cmath>
#include <cstring>
#include "FreeRTOS.h"
#include "cmsis_os.h"
#include "queue.h"
#include "task.h"
#include "usart.h"
#include "BallBeamController.h"
#include "BallStateEstimate.h"
#include "DebugCommand.h"
#include "Serial.h"

extern BallBeamController qd_controller;

namespace {
constexpr uint8_t kPiRxSof = 0xA5U;
constexpr uint8_t kStm32TxSof = 0x5AU;
constexpr uint8_t kCmdModeRequest = 0x06U;
constexpr uint8_t kCmdRunState = 0x07U;
constexpr uint8_t kCmdTuningState = 0x08U;
constexpr uint8_t kCmdRunTelemetry = 0x84U;
constexpr uint8_t kCmdTuningTelemetry = 0x85U;
constexpr uint8_t kCmdModeReply = 0x86U;
constexpr uint32_t kVisionTimeoutMs = 100U;
constexpr int32_t kVisionPositionLimit001cm = 1100;
constexpr float kRadToDeg = 57.2957795f;
UART_HandleTypeDef *const kRaspberryUart = &huart1;

struct __attribute__((packed)) ModeRequestPackage {
    uint8_t sof, cmd;
    uint16_t seq;
    uint8_t mode, crc8;
};

struct __attribute__((packed)) PiRxPackage {
    uint8_t sof, cmd, flags;
    uint16_t seq;
    int32_t ball_pos_001cm, ball_vel_001cms;
    uint32_t pi_time_ms;
    uint8_t task_id;
    uint16_t request_seq;
    uint8_t crc8;
};

struct __attribute__((packed)) TuningRxPackage {
    uint8_t sof, cmd, flags;
    uint16_t seq;
    int32_t ball_pos_001cm, ball_vel_001cms;
    uint32_t pi_time_ms;
    uint8_t task_id;
    uint16_t request_seq;
    int32_t kp_0001, ki_0001, kd_0001, target_v_001cms;
    uint16_t revision;
    uint8_t crc8;
};

struct __attribute__((packed)) ModeReplyPackage {
    uint8_t sof, cmd;
    uint16_t seq;
    uint8_t mode, result, crc8;
};

struct __attribute__((packed)) ControlTelemetry {
    uint8_t sof, cmd, status;
    uint16_t seq;
    int16_t ab_x_001cm, target_x_001cm, ab_v_001cms;
    int16_t angle_001deg, target_angle_001deg, bbp_001deg, trim_001deg;
    uint8_t control_flags, seq_stage;
    uint16_t vision_seq, age_ms;
    int16_t control_x_001cm, control_v_001cms, target_v_001cms;
    uint32_t control_tick_ms, stm32_time_ms;
    uint16_t request_seq;
};
struct __attribute__((packed)) RunTelemetryPackage {
    ControlTelemetry data;
    uint8_t crc8;
};
struct __attribute__((packed)) TuningTelemetryPackage {
    ControlTelemetry data;
    uint16_t revision;
    uint8_t crc8;
};
static_assert(sizeof(ModeRequestPackage) == 6U && sizeof(ModeReplyPackage) == 7U);
static_assert(sizeof(PiRxPackage) == 21U && sizeof(TuningRxPackage) == 39U);
static_assert(sizeof(RunTelemetryPackage) == 42U && sizeof(TuningTelemetryPackage) == 44U);

struct RxEvent { uint8_t size; uint8_t data[sizeof(TuningRxPackage)]; };
struct ModeResponse { uint16_t seq; uint8_t mode, result; };
osMessageQueueId_t rx_queue = nullptr;
osMessageQueueId_t mode_reply_queue = nullptr;
uint8_t raspberry_rx_buffer[128] = {};
uint8_t pi_frame_buffer[sizeof(TuningRxPackage)] = {};
uint16_t pi_frame_bytes = 0;
volatile bool tx_busy = false;
RunTelemetryPackage run_tx = {};
TuningTelemetryPackage tuning_tx = {};
ModeReplyPackage mode_tx = {};
ModeResponse pending_reply = {};
bool has_pending_reply = false;
uint16_t tx_seq = 0;
volatile uint8_t current_mode = COMM_MODE_NONE;
uint32_t generation = 0;
VisionFrame_t latest_vision_frame = {};
bool latest_vision_valid = false;
PiControlRequest_t control_request = {};
bool has_control_request = false;
bool task_succeeded = false, config_succeeded = false;
uint16_t completed_request = 0, completed_revision = 0;

static uint8_t ReverseBits(uint8_t data)
{
    data = static_cast<uint8_t>(((data & 0x55U) << 1U) | ((data & 0xAAU) >> 1U));
    data = static_cast<uint8_t>(((data & 0x33U) << 2U) | ((data & 0xCCU) >> 2U));
    data = static_cast<uint8_t>(((data & 0x0FU) << 4U) | ((data & 0xF0U) >> 4U));
    return data;
}

uint8_t CRC8(const uint8_t *data,
             uint32_t len,
             uint8_t polynomial = 0x07U,
             uint8_t init = 0x00U,
             uint8_t xor_out = 0x00U,
             bool input_invert = false,
             bool output_invert = false)
{
    uint8_t crc = init;
    while (len-- > 0U) {
        crc ^= input_invert ? ReverseBits(*data++) : *data++;
        for (uint8_t i = 0U; i < 8U; ++i) {
            crc = (crc & 0x80U) ? static_cast<uint8_t>((crc << 1U) ^ polynomial)
                                : static_cast<uint8_t>(crc << 1U);
        }
    }
    crc ^= xor_out;
    return output_invert ? ReverseBits(crc) : crc;
}


void StartRaspberryUartReceive()
{
    if (HAL_UARTEx_ReceiveToIdle_DMA(kRaspberryUart, raspberry_rx_buffer,
                                    sizeof(raspberry_rx_buffer)) == HAL_OK) {
        __HAL_DMA_DISABLE_IT(kRaspberryUart->hdmarx, DMA_IT_HT);
    }
}

void ProcessInput(const RxEvent& event)
{
    if (event.data[1] == kCmdModeRequest) {
        const auto& packet = *reinterpret_cast<const ModeRequestPackage *>(event.data);
        if (packet.mode != COMM_MODE_RUN && packet.mode != COMM_MODE_TUNING) {
            return;
        }
        DebugCommand_t command = {};
        command.id = DEBUG_CMD_PI_SET_MODE;
        command.arg1 = packet.mode;
        command.mode_request_seq = packet.seq;
        if (DebugCommandHandle == nullptr ||
            osMessageQueuePut(DebugCommandHandle, &command, 0U, 0U) != osOK) {
            Communication_ReplyMode(packet.mode, packet.seq, 1U);
        }
        return;
    }

    taskENTER_CRITICAL();
    const uint8_t mode = current_mode;
    const uint32_t epoch = generation;
    taskEXIT_CRITICAL();
    if ((mode != COMM_MODE_RUN || event.data[1] != kCmdRunState) &&
        (mode != COMM_MODE_TUNING || event.data[1] != kCmdTuningState)) {
        return; // Only the selected mode's data is accepted.
    }
    const auto& packet = *reinterpret_cast<const PiRxPackage *>(event.data);
    if ((packet.flags & ~1U) != 0U) {
        return;
    }
    VisionFrame_t vision = {};
    vision.ball_pos_001cm = packet.ball_pos_001cm;
    vision.ball_vel_001cms = packet.ball_vel_001cms;
    vision.tracking_valid = packet.flags & 1U;
    vision.seq = packet.seq;
    vision.pi_time_ms = packet.pi_time_ms;
    vision.rx_tick_ms = HAL_GetTick();
    const bool in_range = vision.ball_pos_001cm >= -kVisionPositionLimit001cm &&
                          vision.ball_pos_001cm <= kVisionPositionLimit001cm;
    PiControlRequest_t request = {};
    request.generation = epoch;
    request.mode = mode;
    request.task_id = packet.task_id;
    request.request_seq = packet.request_seq;
    if (mode == COMM_MODE_TUNING) {
        const auto& tuning = *reinterpret_cast<const TuningRxPackage *>(event.data);
        request.kp = tuning.kp_0001 * 0.0001f;
        request.ki = tuning.ki_0001 * 0.0001f;
        request.kd = tuning.kd_0001 * 0.0001f;
        request.target_v_cm_s = tuning.target_v_001cms * 0.01f;
        request.revision = tuning.revision;
    }
    taskENTER_CRITICAL();
    if (epoch != generation) {
        taskEXIT_CRITICAL();
        return;
    }
    if (!vision.tracking_valid || in_range) {
        latest_vision_frame = vision;
        latest_vision_valid = true;
    }
    control_request = request;
    has_control_request = true;
    taskEXIT_CRITICAL();
}

int16_t ToInt16Scaled(float value)
{
    if (!std::isfinite(value)) return 0;
    const long scaled = std::lround(value * 100.0f);
    return static_cast<int16_t>(scaled < -32768 ? -32768 : (scaled > 32767 ? 32767 : scaled));
}

uint8_t TelemetryStatus(uint32_t now)
{
    uint8_t status = (qd_controller.enabled ? 1U : 0U) | (qd_controller.started ? 2U : 0U);
    taskENTER_CRITICAL();
    if (latest_vision_valid && latest_vision_frame.tracking_valid &&
        now - latest_vision_frame.rx_tick_ms <= kVisionTimeoutMs) status |= 4U;
    if (task_succeeded && control_request.request_seq == completed_request) status |= 8U;
    if (config_succeeded && control_request.revision == completed_revision) status |= 16U;
    taskEXIT_CRITICAL();
    return status;
}

void SendModeReply()
{
    if (tx_busy) return;
    if (!has_pending_reply) {
        if (osMessageQueueGet(mode_reply_queue, &pending_reply, nullptr, 0U) != osOK) return;
        has_pending_reply = true;
    }
    mode_tx = {kStm32TxSof, kCmdModeReply, pending_reply.seq,
               pending_reply.mode, pending_reply.result, 0U};
    mode_tx.crc8 = CRC8(reinterpret_cast<const uint8_t *>(&mode_tx), sizeof(mode_tx) - 1U);
    tx_busy = true;
    if (HAL_UART_Transmit_DMA(kRaspberryUart, reinterpret_cast<uint8_t *>(&mode_tx),
                              sizeof(mode_tx)) == HAL_OK) {
        has_pending_reply = false;
    } else {
        tx_busy = false;
    }
}

void SendTelemetry()
{
    if (tx_busy || current_mode == COMM_MODE_NONE) return;
    const uint8_t mode = current_mode;
    ControlTelemetry sample = {};
    BallStateEstimate_t state = {};
    if (BallStateGetLatest(&state) == 0U) {
        state.x_cm = qd_controller.getEstimatedBallX();
        state.vx_cm_s = qd_controller.getEstimatedBallVx();
        const uint32_t last_vision_tick = qd_controller.getLastVisionTick();
        state.vision_age_ms = (last_vision_tick == 0U)
            ? 9999U : (HAL_GetTick() - last_vision_tick);
    }
    const uint32_t now = HAL_GetTick();
    sample.sof = kStm32TxSof;
    sample.cmd = mode == COMM_MODE_TUNING ? kCmdTuningTelemetry : kCmdRunTelemetry;
    sample.seq = tx_seq++;
    sample.ab_x_001cm = ToInt16Scaled(state.x_cm);
    sample.target_x_001cm = ToInt16Scaled(qd_controller.getBallTarget());
    sample.ab_v_001cms = ToInt16Scaled(state.vx_cm_s);
    sample.angle_001deg = ToInt16Scaled(qd_controller.motor_angle * kRadToDeg);
    sample.target_angle_001deg = ToInt16Scaled(qd_controller.getBallAngleCommand() * kRadToDeg);
    sample.bbp_001deg = ToInt16Scaled(qd_controller.getBallBrakePOffsetDeg());
    sample.trim_001deg = ToInt16Scaled(qd_controller.getBallTerminalOffsetDeg());
    sample.control_flags =
        (qd_controller.isBallBrakePActive() ? 1U : 0U) |
        (qd_controller.isBallTerminalPushActive() ? 2U : 0U) |
        (qd_controller.isBallTerminalTrimActive() ? 4U : 0U) |
        (qd_controller.isBallTerminalBrakeGateActive() ? 8U : 0U);
    sample.seq_stage = qd_controller.getBallSequenceStage();
    sample.vision_seq = state.vision_seq;
    sample.age_ms = static_cast<uint16_t>(state.vision_age_ms > 65535U
        ? 65535U : state.vision_age_ms);
    BallBeamController::ControlInputSnapshot control_input = {};
    if (qd_controller.getLastControlInput(&control_input)) {
        sample.control_x_001cm = ToInt16Scaled(control_input.x_cm);
        sample.control_v_001cms = ToInt16Scaled(control_input.vx_cm_s);
        sample.target_v_001cms = ToInt16Scaled(control_input.target_v_cm_s);
        sample.control_tick_ms = control_input.tick_ms;
    } else {
        sample.control_x_001cm = 0;
        sample.control_v_001cms = 0;
        sample.target_v_001cms = 0;
        sample.control_tick_ms = 0U;
    }
    sample.stm32_time_ms = now;

    taskENTER_CRITICAL();
    sample.status = TelemetryStatus(now);
    sample.request_seq = completed_request;
    tuning_tx.revision = completed_revision;
    taskEXIT_CRITICAL();
    uint8_t *data;
    uint16_t size;
    if (mode == COMM_MODE_TUNING) {
        tuning_tx.data = sample;
        data = reinterpret_cast<uint8_t *>(&tuning_tx);
        size = sizeof(tuning_tx);
    } else {
        run_tx.data = sample;
        data = reinterpret_cast<uint8_t *>(&run_tx);
        size = sizeof(run_tx);
    }
    data[size - 1U] = CRC8(data, size - 1U);
    tx_busy = true;
    if (HAL_UART_Transmit_DMA(kRaspberryUart, data, size) != HAL_OK) tx_busy = false;
}
} // namespace

extern "C" void Communication_ApplyMode(uint8_t mode)
{
    taskENTER_CRITICAL();
    current_mode = mode;
    ++generation;
    latest_vision_valid = has_control_request = false;
    task_succeeded = config_succeeded = false;
    taskEXIT_CRITICAL();
}

extern "C" void Communication_ReplyMode(uint8_t mode, uint16_t seq, uint8_t result)
{
    const ModeResponse reply = {seq, mode, result};
    osMessageQueuePut(mode_reply_queue, &reply, 0U, 0U);
}

extern "C" bool Communication_GetControlRequest(PiControlRequest_t *request)
{
    taskENTER_CRITICAL();
    const bool valid = has_control_request;
    if (valid) *request = control_request;
    taskEXIT_CRITICAL();
    return valid;
}

extern "C" void Communication_ReportSuccess(uint32_t epoch, bool parameters,
                                            uint16_t seq, bool success)
{
    taskENTER_CRITICAL();
    if (epoch == generation) {
        if (parameters) {
            completed_revision = seq;
            config_succeeded = success;
        } else {
            completed_request = seq;
            task_succeeded = success;
        }
    }
    taskEXIT_CRITICAL();
}

extern "C" bool Communication_GetLatestVisionFrame(VisionFrame_t *frame, uint32_t max_age_ms)
{
    if (frame == nullptr) return false;
    taskENTER_CRITICAL();
    const bool valid = latest_vision_valid &&
        (max_age_ms == 0U || HAL_GetTick() - latest_vision_frame.rx_tick_ms <= max_age_ms);
    if (valid) *frame = latest_vision_frame;
    taskEXIT_CRITICAL();
    return valid;
}

extern "C" void StartCommunicationTask(void *argument)
{
    (void)argument;
    rx_queue = osMessageQueueNew(8U, sizeof(RxEvent), nullptr);
    mode_reply_queue = osMessageQueueNew(4U, sizeof(ModeResponse), nullptr);
    if (rx_queue == nullptr || mode_reply_queue == nullptr) {
        for (;;) osDelay(100U);
    }
    StartRaspberryUartReceive();
    uint32_t last_tx_ms = HAL_GetTick();
    for (;;) {
        RxEvent event = {};
        while (osMessageQueueGet(rx_queue, &event, nullptr, 0U) == osOK) ProcessInput(event);
        SendModeReply();
        const uint32_t now = HAL_GetTick();
        const uint32_t period = current_mode == COMM_MODE_TUNING ? 5U : 20U;
        if (now - last_tx_ms >= period) {
            SendTelemetry();
            last_tx_ms = now;
        }
        osDelay(1U);
    }
}

static uint16_t PiFrameSize(uint8_t command)
{
    switch (command) {
    case kCmdModeRequest: return sizeof(ModeRequestPackage);
    case kCmdRunState: return sizeof(PiRxPackage);
    case kCmdTuningState: return sizeof(TuningRxPackage);
    default: return 0U;
    }
}

static void DispatchPiFrameFromISR(uint16_t size, BaseType_t *woken)
{
    RxEvent event = {};
    event.size = static_cast<uint8_t>(size);
    std::memcpy(event.data, pi_frame_buffer, size);
    xQueueSendToBackFromISR(reinterpret_cast<QueueHandle_t>(rx_queue), &event, woken);
}

extern "C" void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size)
{
    if (huart == kRaspberryUart) {
        BaseType_t woken = pdFALSE;
        for (uint16_t i = 0; i < Size; ++i) {
            pi_frame_buffer[pi_frame_bytes++] = raspberry_rx_buffer[i];
            while (pi_frame_bytes != 0U) {
                const uint16_t size = pi_frame_bytes >= 2U ? PiFrameSize(pi_frame_buffer[1]) : 0U;
                if (pi_frame_buffer[0] == kPiRxSof && (pi_frame_bytes < 2U || size != 0U)) {
                    if (pi_frame_bytes < size || pi_frame_bytes < 2U) break;
                    if (pi_frame_buffer[size - 1U] == CRC8(pi_frame_buffer, size - 1U)) {
                        DispatchPiFrameFromISR(size, &woken);
                        pi_frame_bytes -= size;
                        std::memmove(pi_frame_buffer, pi_frame_buffer + size, pi_frame_bytes);
                        continue;
                    }
                }
                --pi_frame_bytes;
                std::memmove(pi_frame_buffer, pi_frame_buffer + 1U, pi_frame_bytes);
            }
        }
        portYIELD_FROM_ISR(woken);
        StartRaspberryUartReceive();
    }
}

extern "C" void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart == kRaspberryUart) tx_busy = false;
    Serial_OnTxCplt(huart);
}

extern "C" void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart == kRaspberryUart) {
        __HAL_UNLOCK(huart);
        pi_frame_bytes = 0;
        tx_busy = false;
        StartRaspberryUartReceive();
    }
    Serial_OnError(huart);
}

