#include "AppTelemetry.h"
#include "BallBeamController.h"
#include "BallBeamTasks.h"
#include "BallStateTask.h"

extern BallBeamController qd_controller;
extern BallBeamTasks ball_tasks;

/*
下位机业务进入遥测的出口
*/


// 读取下位机任务状态并返回；此函数不参与Pi请求执行。
PiProtocol::TelemetrySample CollectAppTelemetry(uint32_t now_ms)
{
    constexpr float kRadiansToDegrees = 57.2957795f;
    PiProtocol::TelemetrySample telemetry;
    BallStateEstimate_t ball_estimate = {};
    if (BallStateGetLatest(&ball_estimate) == 0U) {
        ball_estimate.vision_age_ms = 9999U;
    }
    // 读取小球状态
    telemetry.x_cm = ball_estimate.x_cm;
    telemetry.target_x_cm = qd_controller.getBallTarget();
    telemetry.vx_cm_s = ball_estimate.vx_cm_s;
    telemetry.vision_seq = ball_estimate.vision_seq;
    telemetry.vision_age_ms = ball_estimate.vision_age_ms;

    // 读取电机与任务状态
    telemetry.angle_deg = qd_controller.motor_angle * kRadiansToDegrees;
    telemetry.target_angle_deg = qd_controller.getBallAngleCommand() * kRadiansToDegrees;
    telemetry.stage = ball_tasks.getStage();
    telemetry.status = (qd_controller.enabled ? 1U : 0U) | (qd_controller.started ? 2U : 0U); // 电机是否使能 | 是否启动

    // 读取最近一次用于PID控制的数据
    BallBeamController::ControlInputSnapshot control_input = {};
    if (qd_controller.getLastControlInput(&control_input)) {
        telemetry.control_x_cm = control_input.x_cm;
        telemetry.control_v_cm_s = control_input.vx_cm_s;
        telemetry.target_v_cm_s = control_input.target_v_cm_s;
        telemetry.control_tick_ms = control_input.tick_ms;
    }
    telemetry.stm32_time_ms = now_ms;
    return telemetry;
}
