#include "BallBeamTasks.h"

#include <cmath>

/*
下位机任务入口
*/


// 任务启动函数：
//     H题0 -> 5 -> -5。重复启动时先回到固定中心，不重新设置电机零点。
bool PositionSequenceTask::start(const BallStateEstimate_t& state, const VisionData_t& vision, uint32_t now_ms)
{
    if (!IsVisionMeasurementUsable(vision) || now_ms - vision.rx_tick_ms > 100U) return false;
    controller_.applyControlConfig(BallBeamTaskProfiles::Task1.control);
    const float start_x_cm = state.valid ? state.x_cm : state.raw_x_cm;
    const float start_vx_cm_s = state.valid ? state.vx_cm_s : 0.0f;
    const bool return_to_center = std::fabs(start_x_cm) > 0.7f || std::fabs(start_vx_cm_s) > 0.8f;
    phase_ = return_to_center ? Phase::ReturningToCenter : Phase::FirstTarget;
    controller_.startPositionTarget(return_to_center ? 0.0f : BallBeamTaskProfiles::Task1.sequence.first_target);
    return true;
}

// 任务执行函数：
//     H题0 -> 5 -> -5
bool PositionSequenceTask::runCycle(const BallStateEstimate_t& state, uint32_t now_ms)
{
    if (!state.valid || !controller_.isControlUpdateDue(now_ms)) return true;
    const auto& sequence = BallBeamTaskProfiles::Task1.sequence;
    switch (phase_) {
    case Phase::ReturningToCenter:
        if (std::fabs(state.x_cm) <= 0.7f && std::fabs(state.vx_cm_s) <= 0.8f) {
            phase_ = Phase::FirstTarget;
            controller_.setPositionTarget(sequence.first_target);
        }
        break;
    case Phase::FirstTarget:
        if (std::fabs(state.x_cm - sequence.first_target) <= sequence.turn_window &&
            std::fabs(state.vx_cm_s) <= sequence.turn_velocity) {
            phase_ = Phase::SecondTarget;
            controller_.setPositionTarget(sequence.second_target);
        }
        break;
    case Phase::SecondTarget:
        if (std::fabs(state.x_cm - sequence.second_target) <= sequence.turn_window &&
            std::fabs(state.vx_cm_s) <= sequence.turn_velocity) {
            phase_ = Phase::HoldingPosition;
        }
        break;
    case Phase::HoldingPosition:
        break;
    }
    return true; // 序列结束后仍保持最后位置，不自动停机。
}

// 通知目前在任务的哪个阶段
//     H题0 -> 5 -> -5
uint8_t PositionSequenceTask::getStage() const
{
    switch (phase_) {
    case Phase::FirstTarget: return 1U;
    case Phase::SecondTarget: return 2U;
    default: return 0U;
    }
}

// 设置视觉速度目标
bool VelocityTestTask::setTargetVelocity(float target_v_cm_s)
{
    if (!std::isfinite(target_v_cm_s) || std::fabs(target_v_cm_s) < 1.0f ||
        std::fabs(target_v_cm_s) > 5.0f) return false;
    target_velocity_cm_s_ = target_v_cm_s;
    return true;
}

// 配置小球速度测试PID参数
bool VelocityTestTask::configure(float kp, float ki, float kd, float target_v_cm_s)
{
    if (!(kp >= 0 && kp <= 4 && ki >= 0 && ki <= 5 && kd >= 0 && kd <= 0.2f)) return false;
    if (!setTargetVelocity(target_v_cm_s)) return false;
    // 这里只保存本任务参数；启动成功时才交给控制器。
    velocity_kp_ = kp;
    velocity_ki_ = ki;
    velocity_kd_ = kd;
    return true;
}

// 启动视觉速度环任务测试
bool VelocityTestTask::start(const BallStateEstimate_t& state, const VisionData_t& vision, uint32_t now_ms)
{
    if (!IsVisionMeasurementUsable(vision) || now_ms - vision.rx_tick_ms > 100U) return false;
    const uint32_t vision_age_ms = state.vision_age_ms + (now_ms - state.update_tick_ms);
    if (std::fabs(target_velocity_cm_s_) < 1.0f || !state.valid ||
        vision_age_ms > 100U || std::fabs(state.x_cm) > 1.0f ||
        std::fabs(state.vx_cm_s) > 0.7f) return false;

    controller_.applyControlConfig(BallBeamTaskProfiles::Task1.control);
    controller_.setBallVelocityPid(velocity_kp_, velocity_ki_, velocity_kd_);
    start_ms_ = now_ms;
    phase_ = Phase::Running;
    controller_.startVelocityControl(target_velocity_cm_s_);
    return true;
}

// 视觉速度环测试任务执行函数
bool VelocityTestTask::runCycle(const BallStateEstimate_t& state, uint32_t now_ms)
{
    if (!state.valid) {
        finish(true);
        return false;
    }
    if (!controller_.isControlUpdateDue(now_ms)) return true;
    if (std::fabs(state.vx_cm_s) >= 12.0f || now_ms - start_ms_ >= 8000U) {
        finish(true);
        return false;
    }
    if (std::fabs(state.x_cm) >= 6.0f) {
        finish(state.x_cm * target_velocity_cm_s_ < 0.0f);
        return false;
    }
    return true;
}

// 结束小球速度环测试
void VelocityTestTask::finish(bool aborted)
{
    start_ms_ = 0U;
    phase_ = aborted ? Phase::Aborted : Phase::Finished;
    controller_.holdBalance();
}

uint8_t VelocityTestTask::getStage() const
{
    return static_cast<uint8_t>(phase_);
}

// 启动指定任务
bool BallBeamTasks::startTask(TaskId task, const BallStateEstimate_t& state,
                              const VisionData_t& vision, uint32_t now_ms)
{
    BallBeamTask* requested = nullptr;
    switch (task) {
    case TaskId::Task1: requested = &position_task_; break;
    case TaskId::VelocityStep: requested = &velocity_task_; break;
    default: return false;
    }
    if (!requested->start(state, vision, now_ms)) return false;
    if (!controller_.enabled) controller_.enable();
    controller_.start();
    selected_task_ = requested;
    active_task_ = task;
    profile_loaded_ = true;
    return true;
}

// 初始化任务：TASK 0
void BallBeamTasks::initializeTask()
{
    stopTask();
    if (!controller_.enabled) controller_.enable();
    controller_.start();
    controller_.setZeroPoint();         // 设置电机参考角度零点
    controller_.applyControlConfig(BallBeamTaskProfiles::Task1.control);
    profile_loaded_ = true;
    controller_.Ctrl(BallBeamController::CtrlType::AngleCtrl, controller_.getBalanceAngle());
}

// 停止任务
void BallBeamTasks::stopTask()
{
    controller_.disableBalance();
    active_task_ = TaskId::None;
    selected_task_ = nullptr;
}

void BallBeamTasks::stopForModeChange()
{
    if (!isTaskActive()) return;
    stopTask();
    controller_.Ctrl(BallBeamController::CtrlType::AngleCtrl, controller_.getBalanceAngle());
}

// 指定小球位置目标
void BallBeamTasks::startPositionTarget(float target_x_cm)
{
    if (!std::isfinite(target_x_cm) || std::fabs(target_x_cm) > 10.0f) return;
    // 手工位置目标接管控制时，不能再由旧任务的待启动/阶段状态改变目标。
    stopTask();
    if (!profile_loaded_) {
        controller_.applyControlConfig(BallBeamTaskProfiles::Task1.control);
        profile_loaded_ = true;
    }
    controller_.startPositionTarget(target_x_cm);
}

// 指定小球速度目标
bool BallBeamTasks::startVelocityTarget(float target_v_cm_s, const BallStateEstimate_t& state,
                                       const VisionData_t& vision, uint32_t now_ms)
{
    if (!velocity_task_.setTargetVelocity(target_v_cm_s)) return false;
    return startTask(TaskId::VelocityStep, state, vision, now_ms);
}

// 配置小球速度测试PID参数
bool BallBeamTasks::setVelocityTestConfig(float kp, float ki, float kd, float target_v_cm_s)
{
    if (isTaskActive()) return false;
    return velocity_task_.configure(kp, ki, kd, target_v_cm_s);
}

// 执行指定任务
void BallBeamTasks::runCurrentTask(const BallStateEstimate_t& state, uint32_t now_ms)
{
    if (isTaskActive() && !selected_task_->runCycle(state, now_ms)) active_task_ = TaskId::None;
}

// 获取任务执行到哪个阶段
// eg. 0 -> 5 or 5 -> -5
uint8_t BallBeamTasks::getStage() const
{
    return selected_task_ == nullptr ? 0U : selected_task_->getStage();
}
