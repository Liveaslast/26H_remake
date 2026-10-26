#include "cmsis_os.h"
#include "can.h"
#include "DebugCommand.h"
#include "CommunicationTask.h"
#include "QD4310.h"
#include "BallBeamController.h"
#include "BallStateTask.h"
#include "BallBeamTasks.h"
#include <algorithm>
#include <cmath>
#include "BuildMode.h"
#include "MotorTest.h"
#include "PiRequestHandler.h"

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
BallBeamTasks ball_tasks(qd_controller);

namespace {

// 初始化电机使用的CAN1：配置过滤器、启动CAN并开启FIFO0接收中断。
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

// 由CAN接收回调调用：取出一条CAN1报文，匹配电机反馈ID和长度后交给电机对象更新数据。
// 这里只更新反馈，不执行球杆任务或计算闭环。
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

// 在执行手工电机命令前，按需使能并开启电机控制；不等待机械到位或启动球杆任务。
void EnsureMotorReady()
{
    if (!qd_controller.enabled) {
        qd_controller.enable();
    }
    qd_controller.start();
}

// 执行手工平衡角命令（rad）：停止当前球杆任务，修改平衡角，并向电机下达该角度。
void SetBalanceAngleCommand(const float angle_rad)
{
    EnsureMotorReady();
    ball_tasks.stopTask();
    qd_controller.setBalanceAngle(angle_rad);
    qd_controller.Ctrl(BallBeamController::CtrlType::AngleCtrl, qd_controller.getBalanceAngle());
}

// 执行视觉估计器调参命令：读取当前配置，修改指定项，交给BallStateTask后续采用。
// 不在GimbalTask中运行估计器，也不直接修改估计历史。
void ConfigureEstimator(const DebugCommand_t& command)
{
    auto config = BallStateGetEstimatorConfig();
    switch (command.id) {
    case DEBUG_CMD_VISION_SET_AB:
        config.alpha = command.arg1;
        config.beta = command.arg2;
        break;
    case DEBUG_CMD_VISION_SET_LIMITS:
        config.max_velocity_cm_s = command.arg1;
        config.max_x_step_cm = command.arg2;
        break;
    case DEBUG_CMD_VISION_SET_ACTIVE_PREDICTION:
        if (!std::isfinite(command.arg1) || command.arg1 < 0 || command.arg1 > 80) return;
        config.predict_hold_ms = static_cast<uint32_t>(command.arg1);
        config.predict_max_step_cm = command.arg2;
        break;
    case DEBUG_CMD_VISION_SET_MEASUREMENT_DEADBAND:
        if (!std::isfinite(command.arg1)) return;
        config.measurement_deadband_cm = std::max(0.0f, command.arg1);
        break;
    default:
        return;
    }
    BallStateSetEstimatorConfig(config);
}

// 执行一条已解析的USART6调试命令，调用对应的电机、球杆任务或估计器配置接口。
// state和vision提供任务启动所需的数据；具体启动条件仍由对应任务检查。
void ExecuteDebugCommand(const DebugCommand_t& command)
{
    BallStateEstimate_t state = {};
    BallStateGetLatest(&state);
    VisionData_t vision = {};
    Communication_ReadLatestVisionData(&vision, 0U);
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
        ball_tasks.stopTask();
        break;
    case DEBUG_CMD_SET_CURRENT:
        EnsureMotorReady();
        ball_tasks.stopTask();
        qd_controller.Ctrl(BallBeamController::CtrlType::CurrentCtrl, command.arg1);
        break;
    case DEBUG_CMD_SET_SPEED:
        EnsureMotorReady();
        ball_tasks.stopTask();
        qd_controller.Ctrl(BallBeamController::CtrlType::SpeedCtrl, command.arg1);
        break;
    case DEBUG_CMD_SET_ANGLE:
        EnsureMotorReady();
        ball_tasks.stopTask();
        qd_controller.Ctrl(BallBeamController::CtrlType::AngleCtrl, command.arg1);
        break;
    case DEBUG_CMD_SET_STEP_ANGLE:
        EnsureMotorReady();
        ball_tasks.stopTask();
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
        ball_tasks.startPositionTarget(qd_controller.getBallTarget());
        break;
    case DEBUG_CMD_BALL_DISABLE:
        EnsureMotorReady();
        ball_tasks.stopTask();
        qd_controller.Ctrl(BallBeamController::CtrlType::AngleCtrl, qd_controller.getBallAngleCommand());
        break;
    case DEBUG_CMD_BALL_SET_TARGET:
        EnsureMotorReady();
        ball_tasks.startPositionTarget(command.arg1);
        break;
    case DEBUG_CMD_BALL_START_TASK:
        (void)ball_tasks.startTask(static_cast<BallBeamTasks::TaskId>(
            static_cast<uint8_t>(command.arg1)), state, vision, HAL_GetTick());
        break;
    case DEBUG_CMD_BALL_INITIALIZE_TASK:
        ball_tasks.initializeTask();
        break;
    case DEBUG_CMD_BALL_STOP_TASK:
        ball_tasks.stopTask();
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
        (void)ball_tasks.setVelocityTestConfig(command.arg1, command.arg2,
                                              command.arg3, command.arg4);
        break;
    case DEBUG_CMD_BALL_SET_POSITION_PID:
        qd_controller.setBallPositionPid(command.arg1, command.arg2, command.arg3);
        break;
    case DEBUG_CMD_BALL_SET_VELOCITY_PID:
        qd_controller.setBallVelocityPid(command.arg1, command.arg2, command.arg3);
        break;
    case DEBUG_CMD_BALL_SET_TARGET_SPEED:
        (void)ball_tasks.startVelocityTarget(command.arg1, state, vision, HAL_GetTick());
        break;
    case DEBUG_CMD_BALL_SET_POSITION_DEADBAND:
        qd_controller.setBallPositionDeadband(command.arg1);
        break;
    case DEBUG_CMD_BALL_SET_SPEED_LIMIT:
        qd_controller.setBallSpeedLimit(command.arg1);
        break;
    case DEBUG_CMD_VISION_SET_AB:
    case DEBUG_CMD_VISION_SET_LIMITS:
    case DEBUG_CMD_VISION_SET_ACTIVE_PREDICTION:
    case DEBUG_CMD_VISION_SET_MEASUREMENT_DEADBAND:
        ConfigureEstimator(command);
        break;
    case DEBUG_CMD_SET_ZERO_POINT:
        qd_controller.setZeroPoint();
        break;
    case DEBUG_CMD_CLEAR_ZERO_POINT:
        qd_controller.clearZeroPoint();
        EnsureMotorReady();
        qd_controller.Ctrl(BallBeamController::CtrlType::AngleCtrl, qd_controller.motor_angle);
        break;
    case DEBUG_CMD_NONE:
    default:
        break;
    }
}

// 逐条取出并执行USART6调试队列中已有的命令，不等待新命令；文本解析已由DebugTask完成。
void ExecuteQueuedDebugCommands()
{
    if (DebugCommandHandle == nullptr) {
        return;
    }

    DebugCommand_t command = {};
    while (osMessageQueueGet(DebugCommandHandle, &command, nullptr, 0U) == osOK) {
        ExecuteDebugCommand(command);
    }
}


// 读取估计任务保存的小球状态，先运行当前任务以确定目标，再调用球杆控制器计算角度。
// 不在这里做状态估计；记录中的有效位由任务和控制器各自按规则检查。
void RunBallControlCycle()
{
    BallStateEstimate_t state = {};
    if (BallStateGetLatest(&state) != 0U) {
        const uint32_t now_ms = HAL_GetTick();
        ball_tasks.runCurrentTask(state, now_ms);
        qd_controller.updateBalanceControl(state, now_ms);
    }
}
// 启动时反复尝试使能电机，然后设置零电流目标并开启电机控制；不是设机械零点或启动球杆任务。
void EnableMotorAtZeroCurrent()
{
    while (!qd_controller.enabled) {
        qd_controller.enable();
        osDelay(kMotorEnableRetryPeriodMs);
    }
    qd_controller.Ctrl(BallBeamController::CtrlType::CurrentCtrl, 0.0f);
    qd_controller.start();
}

} // namespace

// RTOS执行任务入口：初始化CAN和电机，循环执行调试命令、球杆闭环、Pi请求及电机控制。
// 算法和任务规则由对应组件完成；循环末尾延时1个RTOS tick，不保证整轮耗时恰好1ms。
extern "C" void GimbalTask(void *argument)
{
    (void)argument;

    CAN_InterfaceInit();
    qd_controller.init();
    qd_controller.setAngleLimit(kDefaultAngleLimitMinRad, kDefaultAngleLimitMaxRad);
    EnableMotorAtZeroCurrent();

    PiRequestHandler pi_requests(ball_tasks);
    for (;;) {
        ExecuteQueuedDebugCommands();          // 响应串口命令：执行USART6调试队列中的命令。
        RunBallControlCycle();                 // 视觉闭环控制：读取估计结果，运行当前任务并计算目标角度。
        pi_requests.executePendingRequests();  // 执行Pi模式、任务和参数请求。
        qd_controller.Ctrl_ISR();              // 电机控制计算与电流下发；父类旧名称，当前由任务调用，并非中断。
        osDelay(1);
    }
}

// HAL在CAN FIFO0收到报文时调用的接收回调；正式模式更新电机反馈，测试模式交给MotorTest。
extern "C" void HAL_CAN_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan)
{
#if MOTOR_TEST_MODE
    MotorTest_OnCanRxFifo0MsgPending(hcan);
#else
    UpdateMotorFromCan(hcan);
#endif
}


