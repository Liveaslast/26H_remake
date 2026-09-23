#include "CommunicationTask.h"

#include <cmath>
#include <cstring>

#include "FreeRTOS.h"
#include "cmsis_os.h"
#include "queue.h"
#include "task.h"
#include "usart.h"
#include "BallBeamController.h"
#include "Serial.h"

extern BallBeamController qd_controller;

namespace {

constexpr uint8_t kPiRxSof = 0xA5U;
constexpr uint8_t kStm32TxSof = 0x5AU;
constexpr uint8_t kCmdBallState = 0x07U;
constexpr uint8_t kCmdTelemetry = 0x84U;
constexpr uint8_t kRxFlagTrackingValid = 1U << 0U;
constexpr uint8_t kStatusMotorEnabled = 1U << 0U;
constexpr uint8_t kStatusControlStarted = 1U << 1U;
constexpr uint8_t kStatusVisionValid = 1U << 2U;
constexpr uint32_t kVisionTimeoutMs = 100U;
constexpr uint32_t kTelemetryPeriodMs = 20U;
constexpr float kRadToDeg = 57.2957795f;

UART_HandleTypeDef *const kRaspberryUart = &huart1;

struct __attribute__((packed)) PiRxPackage {
    uint8_t sof;
    uint8_t cmd;
    uint8_t flags;
    uint16_t seq;
    int32_t ball_pos_001cm;
    int32_t ball_vel_001cms;
    uint32_t pi_time_ms;
    uint8_t crc8;
};

struct __attribute__((packed)) Stm32TxPackage {
    uint8_t sof;
    uint8_t cmd;
    uint8_t status;
    uint16_t seq;
    int32_t rod_angle_001deg;
    int32_t motor_angle_001deg;
    int32_t motor_speed_001dps;
    int32_t motor_current_001a;
    uint32_t stm32_time_ms;
    uint8_t fault_code;
    uint8_t crc8;
};

uint8_t raspberry_rx_buffer[sizeof(PiRxPackage)] = {};
Stm32TxPackage tx_package = {};
volatile bool tx_busy = false;
uint16_t tx_seq = 0U;

VisionFrame_t latest_vision_frame = {};
bool latest_vision_valid = false;

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
    std::memset(raspberry_rx_buffer, 0, sizeof(raspberry_rx_buffer));
    if (HAL_UARTEx_ReceiveToIdle_DMA(kRaspberryUart, raspberry_rx_buffer, sizeof(raspberry_rx_buffer)) == HAL_OK) {
        __HAL_DMA_DISABLE_IT(kRaspberryUart->hdmarx, DMA_IT_HT);
    }
}

bool DecodePiRxPackage(uint16_t size, VisionFrame_t *frame)
{
    if ((frame == nullptr) || (size != sizeof(PiRxPackage))) {
        return false;
    }

    const auto *packet = reinterpret_cast<const PiRxPackage *>(raspberry_rx_buffer);
    const uint8_t crc = CRC8(raspberry_rx_buffer, sizeof(PiRxPackage) - 1U);

    if ((packet->sof != kPiRxSof) ||
        (packet->cmd != kCmdBallState) ||
        (packet->crc8 != crc)) {
        return false;
    }

    frame->ball_pos_001cm = packet->ball_pos_001cm;
    frame->ball_vel_001cms = packet->ball_vel_001cms;
    frame->tracking_valid = (packet->flags & kRxFlagTrackingValid) ? 1U : 0U;
    frame->seq = packet->seq;
    frame->pi_time_ms = packet->pi_time_ms;
    frame->rx_tick_ms = HAL_GetTick();
    return true;
}

void StoreLatestVisionFrame(const VisionFrame_t& frame)
{
    taskENTER_CRITICAL();
    latest_vision_frame = frame;
    latest_vision_valid = true;
    taskEXIT_CRITICAL();
}

bool IsVisionFrameFresh(uint32_t now_ms)
{
    bool fresh = false;
    taskENTER_CRITICAL();
    fresh = latest_vision_valid &&
            latest_vision_frame.tracking_valid &&
            ((now_ms - latest_vision_frame.rx_tick_ms) <= kVisionTimeoutMs);
    taskEXIT_CRITICAL();
    return fresh;
}

int32_t ToInt32Scaled(float value, float scale)
{
    if (!std::isfinite(value)) {
        return 0;
    }
    return static_cast<int32_t>(std::lround(value * scale));
}

void SendTelemetry()
{
    if (tx_busy) {
        return;
    }

    const uint32_t now = HAL_GetTick();
    uint8_t status = 0U;

    if (qd_controller.enabled) {
        status |= kStatusMotorEnabled;
    }
    if (qd_controller.started) {
        status |= kStatusControlStarted;
    }
    if (IsVisionFrameFresh(now)) {
        status |= kStatusVisionValid;
    }

    const float motor_angle_deg = qd_controller.motor_angle * kRadToDeg;
    const float motor_speed_deg_s = qd_controller.motor_speed * 6.0f;

    tx_package.sof = kStm32TxSof;
    tx_package.cmd = kCmdTelemetry;
    tx_package.status = status;
    tx_package.seq = tx_seq++;
    tx_package.rod_angle_001deg = ToInt32Scaled(motor_angle_deg, 100.0f);
    tx_package.motor_angle_001deg = ToInt32Scaled(motor_angle_deg, 100.0f);
    tx_package.motor_speed_001dps = ToInt32Scaled(motor_speed_deg_s, 100.0f);
    tx_package.motor_current_001a = ToInt32Scaled(qd_controller.motor_current, 1000.0f);
    tx_package.stm32_time_ms = now;
    tx_package.fault_code = 0U;
    tx_package.crc8 = CRC8(reinterpret_cast<const uint8_t *>(&tx_package), sizeof(tx_package) - 1U);

    tx_busy = true;
    if (HAL_UART_Transmit_DMA(kRaspberryUart, reinterpret_cast<uint8_t *>(&tx_package), sizeof(tx_package)) != HAL_OK) {
        tx_busy = false;
    }
}

} // namespace

extern "C" bool Communication_GetLatestVisionFrame(VisionFrame_t *frame, uint32_t max_age_ms)
{
    if (frame == nullptr) {
        return false;
    }

    const uint32_t now = HAL_GetTick();
    bool valid = false;

    taskENTER_CRITICAL();
    if (latest_vision_valid) {
        *frame = latest_vision_frame;
        valid = (max_age_ms == 0U) || ((now - latest_vision_frame.rx_tick_ms) <= max_age_ms);
    }
    taskEXIT_CRITICAL();

    return valid;
}

extern "C" void StartCommunicationTask(void *argument)
{
    (void)argument;

    while (VisionFrameQueueHandle == nullptr) {
        osDelay(1);
    }

    StartRaspberryUartReceive();

    uint32_t last_tx_ms = HAL_GetTick();
    VisionFrame_t frame = {};

    for (;;) {
        while (osMessageQueueGet(VisionFrameQueueHandle, &frame, nullptr, 0U) == osOK) {
            StoreLatestVisionFrame(frame);
        }

        const uint32_t now = HAL_GetTick();
        if ((now - last_tx_ms) >= kTelemetryPeriodMs) {
            SendTelemetry();
            last_tx_ms = now;
        }

        osDelay(1);
    }
}

extern "C" void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size)
{
    if (huart == kRaspberryUart) {
        VisionFrame_t frame = {};
        if ((VisionFrameQueueHandle != nullptr) && DecodePiRxPackage(Size, &frame)) {
            BaseType_t xHigherPriorityTaskWoken = pdFALSE;
            xQueueSendToBackFromISR(reinterpret_cast<QueueHandle_t>(VisionFrameQueueHandle),
                                    &frame,
                                    &xHigherPriorityTaskWoken);
            portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
        }
        StartRaspberryUartReceive();
    }
}

extern "C" void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart == kRaspberryUart) {
        tx_busy = false;
    }
    Serial_OnTxCplt(huart);
}

extern "C" void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart == kRaspberryUart) {
        __HAL_UNLOCK(huart);
        tx_busy = false;
        StartRaspberryUartReceive();
    }
    Serial_OnError(huart);
}

