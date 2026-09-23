#include "Motortest.h"

#include <algorithm>
#include <cmath>

#include "QD4310.h"
#include "Serial.h"
#include "can.h"

namespace {

constexpr uint8_t kMotorId = 0x00;
constexpr uint32_t kMotorFeedbackStdId = 0x500U + kMotorId;
constexpr float kCurrentStepA = 0.05f;
constexpr float kCurrentLimitA = 0.30f;

QD4310 qd_motor(&hcan1, kMotorId);
float command_current_a = 0.0f;

void PrintFixed2(const char *prefix, const float value, const char *suffix)
{
    long scaled = static_cast<long>(std::lround(static_cast<double>(value) * 100.0));
    const char *sign = "";
    if (scaled < 0) {
        sign = "-";
        scaled = -scaled;
    }
    Serial_Printf("%s%s%ld.%02ld%s", prefix, sign, scaled / 100L, scaled % 100L, suffix);
}

void PrintFixed3(const char *prefix, const float value, const char *suffix)
{
    long scaled = static_cast<long>(std::lround(static_cast<double>(value) * 1000.0));
    const char *sign = "";
    if (scaled < 0) {
        sign = "-";
        scaled = -scaled;
    }
    Serial_Printf("%s%s%ld.%03ld%s", prefix, sign, scaled / 1000L, scaled % 1000L, suffix);
}

void PrintCanStatus()
{
    Serial_Printf("CAN state=%lu err=0x%08lX free=%lu last_status=%lu last_err=0x%08lX last_free=%lu timeout=%lu\r\n",
                  static_cast<unsigned long>(HAL_CAN_GetState(&hcan1)),
                  static_cast<unsigned long>(HAL_CAN_GetError(&hcan1)),
                  static_cast<unsigned long>(HAL_CAN_GetTxMailboxesFreeLevel(&hcan1)),
                  static_cast<unsigned long>(qd_motor.last_tx_status),
                  static_cast<unsigned long>(qd_motor.last_tx_error),
                  static_cast<unsigned long>(qd_motor.last_tx_free_level),
                  static_cast<unsigned long>(qd_motor.last_tx_timed_out));
}

void PrintHelp()
{
    Serial_Printf("\r\nQD4310 bare-metal test commands:\r\n");
    Serial_Printf("  e: enable motor\r\n");
    Serial_Printf("  d: disable motor and clear current\r\n");
    Serial_Printf("  0: set current to 0A\r\n");
    Serial_Printf("  +: current +0.05A, limited to 0.30A\r\n");
    Serial_Printf("  -: current -0.05A, limited to -0.30A\r\n");
    Serial_Printf("  n: send NOP frame\r\n");
    Serial_Printf("  s: print feedback status\r\n");
    Serial_Printf("  c: print CAN status\r\n");
    Serial_Printf("  h or ?: show this help\r\n\r\n");
}

void PrintStatus()
{
    Serial_Printf("QD id=%u enabled=%u ", qd_motor.id, qd_motor.enabled ? 1U : 0U);
    PrintFixed2("cmd_current=", command_current_a, "A ");
    PrintFixed2("feedback_current=", qd_motor.current, "A ");
    PrintFixed2("speed=", qd_motor.speed, "rpm ");
    PrintFixed3("angle=", qd_motor.angle, "rad\r\n");
    PrintCanStatus();
}

void CAN_FilterStart()
{
    CAN_FilterTypeDef filter = {};

    filter.FilterBank = 0;
    filter.FilterMode = CAN_FILTERMODE_IDMASK;
    filter.FilterScale = CAN_FILTERSCALE_32BIT;
    filter.FilterIdHigh = 0x0000;
    filter.FilterIdLow = 0x0000;
    filter.FilterMaskIdHigh = 0x0000;
    filter.FilterMaskIdLow = 0x0000;
    filter.FilterFIFOAssignment = CAN_RX_FIFO0;
    filter.FilterActivation = ENABLE;
    filter.SlaveStartFilterBank = 14;

    if (HAL_CAN_ConfigFilter(&hcan1, &filter) != HAL_OK) {
        Serial_Printf("CAN filter config failed\r\n");
        Error_Handler();
    }

    if (HAL_CAN_Start(&hcan1) != HAL_OK) {
        Serial_Printf("CAN start failed\r\n");
        Error_Handler();
    }

    if (HAL_CAN_ActivateNotification(&hcan1, CAN_IT_RX_FIFO0_MSG_PENDING) != HAL_OK) {
        Serial_Printf("CAN RX notification failed\r\n");
        Error_Handler();
    }
}

void SetCurrent(float current_a)
{
    command_current_a = std::clamp(current_a, -kCurrentLimitA, kCurrentLimitA);
    qd_motor.setCurrent(command_current_a);
    PrintFixed2("set current ", command_current_a, "A\r\n");
    PrintCanStatus();
}

void HandleCommand(uint8_t ch)
{
    switch (ch) {
    case 'e':
    case 'E':
        qd_motor.enable();
        Serial_Printf("enable command sent\r\n");
        PrintCanStatus();
        break;
    case 'd':
    case 'D':
        command_current_a = 0.0f;
        qd_motor.setCurrent(0.0f);
        qd_motor.disable();
        Serial_Printf("disable command sent\r\n");
        PrintCanStatus();
        break;
    case '0':
        SetCurrent(0.0f);
        break;
    case '+':
        SetCurrent(command_current_a + kCurrentStepA);
        break;
    case '-':
        SetCurrent(command_current_a - kCurrentStepA);
        break;
    case 'n':
    case 'N':
        qd_motor.nop();
        Serial_Printf("nop command sent\r\n");
        PrintCanStatus();
        break;
    case 's':
    case 'S':
        PrintStatus();
        break;
    case 'c':
    case 'C':
        PrintCanStatus();
        break;
    case 'h':
    case 'H':
    case '?':
        PrintHelp();
        break;
    case '\r':
    case '\n':
        break;
    default:
        Serial_Printf("unknown command '%c', send h for help\r\n", ch);
        break;
    }
}

} // namespace

extern "C" void MotorTest_Init(void)
{
    Serial_Init();
    CAN_FilterStart();
    PrintHelp();
    Serial_Printf("CAN1 ready, QD4310 test target feedback id=0x%03lX\r\n", kMotorFeedbackStdId);
}

extern "C" void MotorTest_Loop(void)
{
    uint8_t ch = 0U;

    while (Serial_GetRxByte(&ch)) {
        HandleCommand(ch);
    }

    if (Serial_GetRxOverflow()) {
        Serial_ClearRxOverflow();
        Serial_Printf("serial rx overflow cleared\r\n");
    }
}

extern "C" void MotorTest_OnCanRxFifo0MsgPending(CAN_HandleTypeDef *hcan)
{
    CAN_RxHeaderTypeDef rx_header = {};
    uint8_t rx_data[8] = {};

    if (hcan != &hcan1) {
        return;
    }

    if (HAL_CAN_GetRxMessage(hcan, CAN_RX_FIFO0, &rx_header, rx_data) != HAL_OK) {
        return;
    }

    if ((rx_header.IDE == CAN_ID_STD) && (rx_header.StdId == kMotorFeedbackStdId) && (rx_header.DLC == 8U)) {
        qd_motor.update(rx_data);
    }
}


