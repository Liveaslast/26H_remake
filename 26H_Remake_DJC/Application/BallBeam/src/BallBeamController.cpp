#include "BallBeamController.h"

#include <algorithm>
#include <cmath>

#include "FreeRTOS.h"
#include "task.h"

/*
球杆控制器
*/

// 开始一轮控制前清除积分和速度历史，不修改控制参数。
void BallBeamController::resetControlHistory()
{
    position_integral_cm_s = 0.0f;
    velocity_integral_deg = 0.0f;
    has_previous_velocity = false;
    filtered_acceleration_cm_s2 = 0.0f;
    last_control_tick_ms = 0U;
}

// 开启指定的小球控制方式，清除上一轮控制历史，并先向电机下达平衡角。
// 这里只开始小球闭环，不负责使能电机或选择任务。
void BallBeamController::beginControl(ControlMode mode)
{
    taskENTER_CRITICAL();
    has_last_control_input = false;
    last_control_input = {};
    taskEXIT_CRITICAL();
    control_mode = mode;
    resetControlHistory();
    angle_reference_rad = balance_angle_rad;
    last_angle_cmd_rad = angle_reference_rad;
    last_sent_angle_cmd_rad = last_angle_cmd_rad;
    Ctrl(CtrlType::AngleCtrl, last_angle_cmd_rad);
}

// 关闭小球闭环，清除控制历史和最近控制输入记录；不主动改变电机目标或关闭电机。
void BallBeamController::disableBalance()
{
    taskENTER_CRITICAL();
    has_last_control_input = false;
    last_control_input = {};
    taskEXIT_CRITICAL();
    control_mode = ControlMode::Disabled;
    target_velocity_cm_s = 0.0f;
    resetControlHistory();
}

// 用传入配置替换当前PID、前馈、角度限制和控制周期，并清除算法历史。
// 不保留上一任务的调参值，也不在这里启动任务。
void BallBeamController::applyControlConfig(const BallBeamControlConfig& config)
{
    setBalanceAngle(config.balance_angle_deg * kDegToRad);
    position_velocity_gains = config.position_velocity;
    resetControlHistory();
    setBallFeedforwardSplit(config.feedforward.positive, config.feedforward.negative);
    setBallAngleLimit(config.angle_command_limit_deg);
    setBallPositionDeadband(config.x_deadband_cm);
    setBallOuterLoopPeriod(config.outer_loop_period_ms);
    setAngleRateLimit(config.angle_rate_deg_per_s * kDegToRad);
}

// 开启位置控制：接收±10cm内的目标位置，清除历史，并先下达平衡角。
void BallBeamController::startPositionTarget(const float target_x_cm_)
{
    if (!std::isfinite(target_x_cm_) || std::fabs(target_x_cm_) > 10.0f) return;
    target_velocity_cm_s = 0.0f;
    setPositionTarget(target_x_cm_);
    beginControl(ControlMode::Position);
}

// 切换目标位置（cm），清除位置环和速度环积分；不改变当前控制方式，不直接下达角度。
void BallBeamController::setPositionTarget(const float target_x_cm_)
{
    target_x_cm = target_x_cm_;
    position_integral_cm_s = 0.0f;
    velocity_integral_deg = 0.0f;
    last_control_tick_ms = 0U;
}

// 设置球杆平衡时对应的电机角度（rad），更新角度计算基准；本函数不直接下达电机指令。
void BallBeamController::setBalanceAngle(const float angle_rad)
{
    if (!std::isfinite(angle_rad)) {
        return;
    }
    balance_angle_rad = angle_rad;
    angle_reference_rad = balance_angle_rad;
    last_angle_cmd_rad = angle_reference_rad;
    last_sent_angle_cmd_rad = last_angle_cmd_rad;
    velocity_integral_deg = 0.0f;
    last_control_tick_ms = 0U;
}

// 设置正、负目标位置各自采用的前馈系数（度/cm）；不是按小球运动方向选择。
void BallBeamController::setBallFeedforwardSplit(const float pos_target_deg_per_cm,
                                                 const float neg_target_deg_per_cm)
{
    if (std::isfinite(pos_target_deg_per_cm)) {
        target_feedforward_pos_deg_per_cm = pos_target_deg_per_cm;
    }
    if (std::isfinite(neg_target_deg_per_cm)) {
        target_feedforward_neg_deg_per_cm = neg_target_deg_per_cm;
    }
}

// 限制小球闭环相对平衡角最多修正多少度；不是电机的绝对角度限位。
void BallBeamController::setBallAngleLimit(const float max_delta_deg)
{
    if (std::isfinite(max_delta_deg)) {
        max_angle_delta_deg = std::max(0.0f, max_delta_deg);
    }
}

// 设置小球闭环的计算间隔（ms，限制为5~100）；下次有效更新可立即计算。
void BallBeamController::setBallOuterLoopPeriod(const float period_ms)
{
    if (!std::isfinite(period_ms)) {
        return;
    }

    ball_outer_loop_period_ms =
        static_cast<uint32_t>(std::clamp(period_ms, 5.0f, 100.0f));
    last_control_tick_ms = 0U;
}

// 修改当前位置环PID并清除位置积分；位置环的输出是目标速度，不是电机角度。
void BallBeamController::setBallPositionPid(const float kp, const float ki, const float kd)
{
    if (!std::isfinite(kp) || !std::isfinite(ki) || !std::isfinite(kd) ||
        kp < 0.0f || ki < 0.0f || kd < 0.0f) {
        return;
    }
    position_velocity_gains.position_kp_per_s = kp;
    position_velocity_gains.position_ki_per_s2 = ki;
    position_velocity_gains.position_kd = kd;
    position_integral_cm_s = 0.0f;
}

// 修改两种控制方式共用的速度环PID，并清除速度积分和微分历史。
// 只修改当前控制参数；不会替速度测试任务保存下一次测试配置。
void BallBeamController::setBallVelocityPid(const float kp, const float ki, const float kd)
{
    if (!std::isfinite(kp) || !std::isfinite(ki) || !std::isfinite(kd) ||
        kp < 0.0f || kp > 4.0f || ki < 0.0f || ki > 5.0f ||
        kd < 0.0f || kd > 0.2f) {
        return;
    }
    position_velocity_gains.velocity_kp_deg_per_cm_s = kp;
    position_velocity_gains.velocity_ki_deg_per_cm = ki;
    position_velocity_gains.velocity_kd_deg_s_per_cm_s = kd;
    velocity_integral_deg = 0.0f;
    has_previous_velocity = false;
    filtered_acceleration_cm_s2 = 0.0f;
}

// 设置位置误差死区（cm）；误差绝对值小于此值时，位置控制按零误差处理。
void BallBeamController::setBallPositionDeadband(const float deadband_cm)
{
    if (std::isfinite(deadband_cm)) {
        x_deadband_cm = std::max(0.0f, deadband_cm);
    }
}

// 限制位置环生成的目标速度绝对值（cm/s）；不修改固定速度控制的给定目标。
void BallBeamController::setBallSpeedLimit(const float max_target_v_cm_s)
{
    if (std::isfinite(max_target_v_cm_s) && max_target_v_cm_s > 0.0f &&
        max_target_v_cm_s <= 12.0f) {
        position_velocity_gains.max_target_velocity_cm_s = max_target_v_cm_s;
    }
}

// 供遥测复制最近一次真实控制计算的时间、位置、速度和目标速度；没有记录时返回false。
// 返回true只表示有记录，不保证它仍然新鲜；调用者可通过tick_ms判断时间。
bool BallBeamController::getLastControlInput(ControlInputSnapshot *snapshot) const
{
    if (snapshot == nullptr) {
        return false;
    }
    taskENTER_CRITICAL();
    const bool available = has_last_control_input;
    if (available) {
        *snapshot = last_control_input;
    }
    taskEXIT_CRITICAL();
    return available;
}

// 设置角度指令更新阈值（度）；与上次提交角度相差过小时，不重复向父类提交指令。
void BallBeamController::setAngleCommandDeadband(const float deadband_deg)
{
    if (std::isfinite(deadband_deg)) {
        angle_cmd_deadband_deg = std::max(0.0f, deadband_deg);
    }
}

// GimbalTask周期调用：根据估计位置/速度（cm、cm/s）和MCU当前时间（ms）计算目标电机角度。
// 先确定目标速度和积分规则，再算速度PID，最后叠加前馈并输出；估计无效时跳过，不自动停机。
void BallBeamController::updateBalanceControl(const BallStateEstimate_t& state, const uint32_t now_ms)
{
    if (control_mode == ControlMode::Disabled) {
        return;
    }

    if (state.valid == 0U) {
        velocity_integral_deg = 0.0f;
        last_control_tick_ms = 0U;
        return;
    }

    if (!isControlUpdateDue(now_ms)) return;

    const float dt_s = (last_control_tick_ms == 0U)
                           ? static_cast<float>(ball_outer_loop_period_ms) * 0.001f
                           : static_cast<float>(now_ms - last_control_tick_ms) * 0.001f;
    last_control_tick_ms = now_ms;

    float target_v_cm_s = target_velocity_cm_s;
    float feedforward_deg = 0.0f;
    VelocityLoopRules rules;
    if (control_mode == ControlMode::Position) {
        float error_cm = target_x_cm - state.x_cm;
        if (std::fabs(error_cm) < x_deadband_cm) error_cm = 0.0f;
        target_v_cm_s = calculatePositionVelocity(state, error_cm, dt_s);
        feedforward_deg = target_x_cm * ((target_x_cm >= 0.0f)
            ? target_feedforward_pos_deg_per_cm : target_feedforward_neg_deg_per_cm);
        rules = calculatePositionVelocityRules(error_cm, state.vx_cm_s, feedforward_deg);
    }
    const float feedback_deg = calculateVelocityCorrection(state.vx_cm_s, target_v_cm_s, dt_s, rules);
    outputAngle(feedforward_deg + feedback_deg, state, target_v_cm_s, now_ms);
}

// 位置环只负责根据位置误差生成限幅后的目标速度。
// 输入误差已经过死区处理，dt_s为计算间隔（秒）；函数会更新位置积分，返回单位为cm/s。
float BallBeamController::calculatePositionVelocity(const BallStateEstimate_t& state,
                                                    float error_cm, float dt_s)
{
    const auto& gains = position_velocity_gains;
    const float position_p_cm_s = gains.position_kp_per_s * error_cm;
    const float position_d_cm_s = -gains.position_kd * state.vx_cm_s;
    const float proposed_position_integral = std::clamp(
        position_integral_cm_s + error_cm * dt_s, -10.0f, 10.0f);
    const float proposed_target_v = position_p_cm_s + position_d_cm_s +
        gains.position_ki_per_s2 * proposed_position_integral;
    if (!((proposed_target_v > gains.max_target_velocity_cm_s && error_cm > 0.0f) ||
          (proposed_target_v < -gains.max_target_velocity_cm_s && error_cm < 0.0f))) {
        position_integral_cm_s = proposed_position_integral;
    }
    return std::clamp(
        position_p_cm_s + position_d_cm_s +
            gains.position_ki_per_s2 * position_integral_cm_s,
        -gains.max_target_velocity_cm_s,
        gains.max_target_velocity_cm_s);
}

// 位置控制决定何时积累积分，以及前馈后还剩多少角度空间；不修改PID历史。
// 返回积分权重、泄漏率和限幅规则，交给共用速度环采用；不直接计算电机角度。
BallBeamController::VelocityLoopRules BallBeamController::calculatePositionVelocityRules(
    float error_cm, float velocity_cm_s, float feedforward_deg) const
{
    const auto& gains = position_velocity_gains;
    const float error_weight = std::clamp(
        (gains.integral_zero_error_cm - std::fabs(error_cm)) /
            std::max(0.001f, gains.integral_zero_error_cm - gains.integral_full_error_cm),
        0.0f, 1.0f);
    const float speed_weight = std::clamp(
        (gains.integral_zero_speed_cm_s - std::fabs(velocity_cm_s)) /
            std::max(0.001f, gains.integral_zero_speed_cm_s - gains.integral_full_speed_cm_s),
        0.0f, 1.0f);
    VelocityLoopRules rules;
    rules.integral_weight = (error_cm != 0.0f &&
        (!gains.integral_negative_target_only || target_x_cm < 0.0f))
        ? error_weight * speed_weight : 0.0f;
    rules.integral_leak_per_s = gains.integral_leak_per_s;
    rules.integral_limit_deg = gains.max_velocity_integral_deg;
    rules.feedback_limit_deg = gains.max_feedback_angle_deg;
    // 同时满足反馈限幅和“前馈+反馈”的总限幅，超出时不再向该方向积累积分。
    rules.integration_lower_deg = std::max(-gains.max_feedback_angle_deg,
                                            -max_angle_delta_deg - feedforward_deg);
    rules.integration_upper_deg = std::min(gains.max_feedback_angle_deg,
                                            max_angle_delta_deg - feedforward_deg);
    return rules;
}

// 对速度差分做原有平滑，得到速度PID的D项（角度单位为度）。
// 输入速度单位为cm/s、间隔为秒；每次调用会保存本次速度及平滑后的加速度。
float BallBeamController::calculateVelocityDerivative(float velocity_cm_s, float dt_s)
{
    const float measured_accel_cm_s2 = (has_previous_velocity && dt_s > 0.0f)
        ? (velocity_cm_s - previous_velocity_cm_s) / dt_s : 0.0f;
    previous_velocity_cm_s = velocity_cm_s;
    has_previous_velocity = true;
    filtered_acceleration_cm_s2 =
        0.75f * filtered_acceleration_cm_s2 + 0.25f * measured_accel_cm_s2;
    return -position_velocity_gains.velocity_kd_deg_s_per_cm_s *
        filtered_acceleration_cm_s2;
}

// 只计算速度PID反馈，不读取位置目标、位置误差或控制方式。
// 按本轮规则处理积分泄漏、限幅和抗饱和，更新积分及微分历史，返回反馈角度（度，不含前馈）。
float BallBeamController::calculateVelocityCorrection(float velocity_cm_s, float target_v_cm_s,
                                                      float dt_s, const VelocityLoopRules& rules)
{
    const auto& gains = position_velocity_gains;
    const float velocity_error_cm_s = target_v_cm_s - velocity_cm_s;
    const float p_deg = gains.velocity_kp_deg_per_cm_s * velocity_error_cm_s;
    const float d_deg = calculateVelocityDerivative(velocity_cm_s, dt_s);
    if (rules.integral_weight == 0.0f) {
        velocity_integral_deg *= std::clamp(
            1.0f - rules.integral_leak_per_s * dt_s, 0.0f, 1.0f);
    }
    const float candidate_integral_deg = std::clamp(
        velocity_integral_deg + gains.velocity_ki_deg_per_cm * velocity_error_cm_s *
            rules.integral_weight * dt_s,
        -rules.integral_limit_deg, rules.integral_limit_deg);
    const float candidate_feedback_deg = p_deg + candidate_integral_deg + d_deg;
    const bool pushing_upper_limit = (velocity_error_cm_s > 0.0f) &&
        candidate_feedback_deg > rules.integration_upper_deg;
    const bool pushing_lower_limit = (velocity_error_cm_s < 0.0f) &&
        candidate_feedback_deg < rules.integration_lower_deg;
    if (!pushing_upper_limit && !pushing_lower_limit) {
        velocity_integral_deg = candidate_integral_deg;
    }
    return std::clamp(p_deg + velocity_integral_deg + d_deg,
                      -rules.feedback_limit_deg, rules.feedback_limit_deg);
}

// 统一限幅、保存本次真实控制输入，并向电机控制器提交角度。
// correction_deg是前馈与反馈之和（度）；转换为rad并叠加平衡角，达到更新阈值才提交给父类。
void BallBeamController::outputAngle(float correction_deg, const BallStateEstimate_t& state,
                                     float target_v_cm_s, uint32_t now_ms)
{
    last_angle_cmd_rad = std::clamp(
        angle_reference_rad + correction_deg * kDegToRad,
        angle_reference_rad - max_angle_delta_deg * kDegToRad,
        angle_reference_rad + max_angle_delta_deg * kDegToRad);
    taskENTER_CRITICAL();
    last_control_input = {now_ms, state.x_cm, state.vx_cm_s, target_v_cm_s};
    has_last_control_input = true;
    taskEXIT_CRITICAL();
    if (std::fabs(last_angle_cmd_rad - last_sent_angle_cmd_rad) >=
        angle_cmd_deadband_deg * kDegToRad) {
        last_sent_angle_cmd_rad = last_angle_cmd_rad;
        Ctrl(CtrlType::AngleCtrl, last_sent_angle_cmd_rad);
    }
}

// 判断小球闭环是否已开启且到了计算时间（MCU毫秒）；首次更新可立即计算，不在这里修改状态。
bool BallBeamController::isControlUpdateDue(uint32_t now_ms) const
{
    return control_mode != ControlMode::Disabled &&
        (last_control_tick_ms == 0U || now_ms - last_control_tick_ms >= ball_outer_loop_period_ms);
}

// 开启固定速度控制（目标单位cm/s，允许零目标），清除历史并先下达平衡角。
// 任务允许的速度范围由调用它的任务检查，本函数不负责任务启动条件。
void BallBeamController::startVelocityControl(float target_v_cm_s)
{
    target_velocity_cm_s = target_v_cm_s;
    setPositionTarget(0.0f);
    beginControl(ControlMode::Velocity);
}

// 结束小球闭环并向电机下达平衡角；保留最后一次真实控制输入，不伪造新记录。
// 下达角度不表示机械已经到位，也不表示小球已经停止。
void BallBeamController::holdBalance()
{
    control_mode = ControlMode::Disabled;
    target_velocity_cm_s = 0.0f;
    resetControlHistory();
    last_angle_cmd_rad = last_sent_angle_cmd_rad = balance_angle_rad;
    Ctrl(CtrlType::AngleCtrl, balance_angle_rad);
}
