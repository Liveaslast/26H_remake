#include "cmsis_os.h"
#include "can.h"
#include "DebugCommand.h"
#include "CommunicationTask.h"
#include "QD4310.h"
#include "BallBeamController.h"
#include "BallStateEstimate.h"
#include "BuildMode.h"
#include "Motortest.h"
#include "PiControl.h"

constexpr uint8_t kMotorId = 0x00;
constexpr uint32_t kMotorFeedbackStdId = 0x500U + kMotorId;
constexpr float kControlTs = 0.001f;
constexpr float kCurrentLimit = 0.60f;
constexpr uint32_t kMotorEnableRetryPeriodMs = 5U;
constexpr float kDefaultAngleLimitMinRad = 11.5f * std::numbers::pi_v<float> / 180.0f;
constexpr float kDefaultAngleLimitMaxRad = 29.5f * std::numbers::pi_v<float> / 180.0f;

QD4310 qd_motor(&hcan1, kMotorId);

PID speed_pid{
    PID::position_type,
    0.01f,
    0.0f,
    0.0f,
    2000.0f,
    -2000.0f,
    kCurrentLimit,
    -kCurrentLimit
};

PID angle_pid{
    PID::position_type,
    8.0f,
    0.17f,
    200.0f,
    1.8f,
    -1.8f,
    kCurrentLimit,
    -kCurrentLimit
};

BallBeamController qd_controller(qd_motor, speed_pid, angle_pid, kControlTs, kCurrentLimit);

namespace {

void CAN_InterfaceInit()
{
    CAN_FilterTypeDef filter = {};

    filter.FilterBank = 0;
    filter.FilterMode = CAN_FILTERMODE_IDMASK;
    filter.FilterScale = CAN_FILTERSCALE_32BIT;
    filter.FilterIdLow = 0x0000;
    filter.FilterIdHigh = 0x0000;
    filter.FilterMaskIdLow = 0x0000;
    filter.FilterMaskIdHigh = 0x0000;
    filter.FilterFIFOAssignment = CAN_RX_FIFO0;
    filter.FilterActivation = ENABLE;
    filter.SlaveStartFilterBank = 14;

    if (HAL_CAN_ConfigFilter(&hcan1, &filter) != HAL_OK) {
        Error_Handler();
    }
    if (HAL_CAN_Start(&hcan1) != HAL_OK) {
        Error_Handler();
    }
    if (HAL_CAN_ActivateNotification(&hcan1, CAN_IT_RX_FIFO0_MSG_PENDING) != HAL_OK) {
        Error_Handler();
    }
}

void UpdateMotorFromCan(CAN_HandleTypeDef *hcan)
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

void EnsureMotorReady()
{
    if (!qd_controller.enabled) {
        qd_controller.enable();
    }
    qd_controller.start();
}

void SetBalanceAngleCommand(const float angle_rad)
{
    EnsureMotorReady();
    qd_controller.disableBalance();
    qd_controller.setBalanceAngle(angle_rad);
    qd_controller.Ctrl(BallBeamController::CtrlType::AngleCtrl, qd_controller.getBalanceAngle());
}

void ExecuteDebugCommand(const DebugCommand_t& command)
{
    switch (command.id) {
    case DEBUG_CMD_ENABLE:
        qd_controller.enable();
        break;
    case DEBUG_CMD_DISABLE:
        qd_controller.disable();
        break;
    case DEBUG_CMD_START:
        qd_controller.start();
        break;
    case DEBUG_CMD_STOP:
        qd_controller.stop();
        qd_controller.disableBalance();
        break;
    case DEBUG_CMD_SET_CURRENT:
        EnsureMotorReady();
        qd_controller.disableBalance();
        qd_controller.Ctrl(BallBeamController::CtrlType::CurrentCtrl, command.arg1);
        break;
    case DEBUG_CMD_SET_SPEED:
        EnsureMotorReady();
        qd_controller.disableBalance();
        qd_controller.Ctrl(BallBeamController::CtrlType::SpeedCtrl, command.arg1);
        break;
    case DEBUG_CMD_SET_ANGLE:
        EnsureMotorReady();
        qd_controller.disableBalance();
        qd_controller.Ctrl(BallBeamController::CtrlType::AngleCtrl, command.arg1);
        break;
    case DEBUG_CMD_SET_STEP_ANGLE:
        EnsureMotorReady();
        qd_controller.disableBalance();
        qd_controller.Ctrl(BallBeamController::CtrlType::StepAngleCtrl, command.arg1);
        break;
    case DEBUG_CMD_SET_SPEED_PID:
        qd_controller.setSpeedPID(command.arg1, command.arg2, command.arg3);
        break;
    case DEBUG_CMD_SET_ANGLE_PID:
        qd_controller.setAnglePID(command.arg1, command.arg2, command.arg3);
        break;
    case DEBUG_CMD_SET_CURRENT_LIMIT:
        qd_controller.setCurrentLimit(command.arg1);
        break;
    case DEBUG_CMD_SET_ANGLE_LIMIT:
        qd_controller.setAngleLimit(command.arg1, command.arg2);
        break;
    case DEBUG_CMD_DISABLE_ANGLE_LIMIT:
        qd_controller.disableAngleLimit();
        break;
    case DEBUG_CMD_SET_ANGLE_RATE_LIMIT:
        qd_controller.setAngleRateLimit(command.arg1);
        break;
    case DEBUG_CMD_SET_ANGLE_CMD_DEADBAND:
        qd_controller.setAngleCommandDeadband(command.arg1);
        break;
    case DEBUG_CMD_BALL_ENABLE:
        EnsureMotorReady();
        qd_controller.startPositionTarget(qd_controller.getBallTarget());
        break;
    case DEBUG_CMD_BALL_DISABLE:
        EnsureMotorReady();
        qd_controller.disableBalance();
        qd_controller.Ctrl(BallBeamController::CtrlType::AngleCtrl, qd_controller.getBallAngleCommand());
        break;
    case DEBUG_CMD_BALL_SET_TARGET:
        EnsureMotorReady();
        qd_controller.startPositionTarget(command.arg1);
        break;
    case DEBUG_CMD_BALL_START_TASK:
        EnsureMotorReady();
        (void)qd_controller.startTask(static_cast<BallBeamController::TaskId>(
            static_cast<uint8_t>(command.arg1)));
        break;
    case DEBUG_CMD_BALL_INITIALIZE_TASK:
        EnsureMotorReady();
        qd_controller.initializeTask();
        break;
    case DEBUG_CMD_BALL_STOP_TASK:
        qd_controller.stopTask();
        break;
    case DEBUG_CMD_BALL_SET_BALANCE_ANGLE:
        SetBalanceAngleCommand(command.arg1);
        break;
    case DEBUG_CMD_BALL_SET_FEEDFORWARD_SPLIT:
        qd_controller.setBallFeedforwardSplit(command.arg1, command.arg2);
        break;
    case DEBUG_CMD_BALL_SET_ANGLE_LIMIT:
        qd_controller.setBallAngleLimit(command.arg1);
        break;
    case DEBUG_CMD_BALL_SET_RATE:
        qd_controller.setBallOuterLoopPeriod(command.arg1);
        break;
    case DEBUG_CMD_BALL_SET_VELOCITY_TEST_CONFIG:
        if (!qd_controller.isTaskActive()) {
            qd_controller.setVelocityTestConfig(command.arg1, command.arg2,
                                                command.arg3, command.arg4);
        }
        break;
    case DEBUG_CMD_BALL_SET_POSITION_PID:
        qd_controller.setBallPositionPid(command.arg1, command.arg2, command.arg3);
        break;
    case DEBUG_CMD_BALL_SET_VELOCITY_PID:
        qd_controller.setBallVelocityPid(command.arg1, command.arg2, command.arg3);
        break;
    case DEBUG_CMD_BALL_SET_TARGET_SPEED:
        EnsureMotorReady();
        (void)qd_controller.startVelocityTarget(command.arg1);
        break;
    case DEBUG_CMD_BALL_SET_POSITION_DEADBAND:
        qd_controller.setBallPositionDeadband(command.arg1);
        break;
    case DEBUG_CMD_BALL_SET_SPEED_LIMIT:
        qd_controller.setBallSpeedLimit(command.arg1);
        break;
    case DEBUG_CMD_VISION_SET_AB:
        qd_controller.setVisionAb(command.arg1, command.arg2);
        break;
    case DEBUG_CMD_VISION_SET_LIMITS:
        qd_controller.setVisionActiveLimits(command.arg1, command.arg2);
        break;
    case DEBUG_CMD_VISION_SET_ACTIVE_PREDICTION:
        qd_controller.setVisionActivePrediction(command.arg1, command.arg2);
        break;
    case DEBUG_CMD_VISION_SET_MEASUREMENT_DEADBAND:
        qd_controller.setVisionMeasurementDeadband(command.arg1);
        break;
    case DEBUG_CMD_SET_ZERO_POINT:
        qd_controller.setZeroPoint();
        break;
    case DEBUG_CMD_CLEAR_ZERO_POINT:
        qd_controller.clearZeroPoint();
        EnsureMotorReady();
        qd_controller.Ctrl(BallBeamController::CtrlType::AngleCtrl, qd_controller.motor_angle);
        break;
    case DEBUG_CMD_PI_SET_MODE:
        if (qd_controller.isTaskActive()) {
            qd_controller.stopTask();
            qd_controller.Ctrl(BallBeamController::CtrlType::AngleCtrl, qd_controller.getBalanceAngle());
        }
        Communication_ApplyMode(static_cast<uint8_t>(command.arg1));
        Communication_ReplyMode(static_cast<uint8_t>(command.arg1), command.mode_request_seq, 0U);
        break;
    case DEBUG_CMD_NONE:
    default:
        break;
    }
}

void ProcessDebugCommands()
{
    if (DebugCommandHandle == nullptr) {
        return;
    }

    DebugCommand_t command = {};
    while (osMessageQueueGet(DebugCommandHandle, &command, nullptr, 0U) == osOK) {
        ExecuteDebugCommand(command);
    }
}

void ProcessBallState()
{
    if (BallStateQueueHandle == nullptr) {
        return;
    }

    BallStateEstimate_t state = {};
    bool has_state = false;
    while (osMessageQueueGet(BallStateQueueHandle, &state, nullptr, 0U) == osOK) {
        has_state = true;
    }

    if (!has_state && (BallStateGetLatest(&state) != 0U)) {
        has_state = true;
    }

    if (has_state) {
        qd_controller.updateBalanceControl(state, HAL_GetTick());
    }
}

void AutoEnableMotor()
{
    while (!qd_controller.enabled) {
        qd_controller.enable();
        osDelay(kMotorEnableRetryPeriodMs);
    }
    qd_controller.Ctrl(BallBeamController::CtrlType::CurrentCtrl, 0.0f);
    qd_controller.start();
}

} // namespace

extern "C" void GimbalTask(void *argument)
{
    (void)argument;

    CAN_InterfaceInit();
    qd_controller.init();
    qd_controller.setAngleLimit(kDefaultAngleLimitMinRad, kDefaultAngleLimitMaxRad);
    AutoEnableMotor();

    for (;;) {
        ProcessDebugCommands();
        ProcessBallState();
        static PiControlExecutor pi_control(qd_controller);
        pi_control.process();
        qd_controller.Ctrl_ISR();
        osDelay(1);
    }
}

extern "C" void HAL_CAN_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan)
{
#if MOTOR_TEST_MODE
    MotorTest_OnCanRxFifo0MsgPending(hcan);
#else
    UpdateMotorFromCan(hcan);
#endif
}


