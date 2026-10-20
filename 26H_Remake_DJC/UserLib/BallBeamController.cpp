#include "BallBeamController.h"

#include <algorithm>
#include <cmath>

#include "FreeRTOS.h"
#include "task.h"

namespace {

constexpr uint32_t kMinimumEstimatorDtMs = 5U;

} // namespace

void BallBeamController::enableBalance()
{
    taskENTER_CRITICAL();
    has_last_control_input = false;
    last_control_input = {};
    taskEXIT_CRITICAL();
    balance_enabled = true;
    has_control_vision_seq = false;
    has_last_control_x = false;
    last_raw_control_dx_cm = 0.0f;
    last_control_dx_cm = 0.0f;
    ball_error_integral_cm_s = 0.0f;
    velocity_integral_deg = 0.0f;
    last_error_cm = 0.0f;
    velocity_test_has_previous_v = false;
    velocity_test_d_filtered_cm_s2 = 0.0f;
    previous_error_cm = 0.0f;
    previous_previous_error_cm = 0.0f;
    has_incremental_pid_history = false;
    last_control_tick_ms = 0U;
    angle_reference_rad = balance_angle_rad;
    last_angle_cmd_rad = angle_reference_rad;
    last_sent_angle_cmd_rad = last_angle_cmd_rad;
    last_brake_p_offset_deg = 0.0f;
    terminal_correction_latched = false;
    last_brake_p_active = false;
    last_terminal_push_active = false;
    last_terminal_trim_active = false;
    last_terminal_brake_gate_active = false;
    last_stalled_before_terminal = false;
    Ctrl(CtrlType::AngleCtrl, last_angle_cmd_rad);
}

void BallBeamController::disableBalance()
{
    taskENTER_CRITICAL();
    has_last_control_input = false;
    last_control_input = {};
    taskEXIT_CRITICAL();
    balance_enabled = false;
    velocity_integral_deg = 0.0f;
    brake_p_active = false;
    brake_p_active_direction = 0.0f;
    target_motion_direction = 0.0f;
    ball_sequence_active = false;
    ball_sequence_stage = 0U;
    task_start_pending = false;
    last_terminal_trim_deg = 0.0f;
    terminal_correction_latched = false;
    last_brake_p_offset_deg = 0.0f;
    last_brake_p_active = false;
    last_terminal_push_active = false;
    last_terminal_trim_active = false;
    last_terminal_brake_gate_active = false;
    last_stalled_before_terminal = false;
    active_task = TaskId::None;
    velocity_test_command_cm_s = 0.0f;
    velocity_test_start_ms = 0U;
    velocity_test_has_previous_v = false;
    velocity_test_d_filtered_cm_s2 = 0.0f;
}

void BallBeamController::applyTaskProfile(const BallBeamTaskProfile& profile)
{
    setBalanceAngle(profile.balance_angle_deg * kDegToRad);
    task_control_mode = profile.control_mode;
    position_velocity_gains = profile.position_velocity;
    if (position_pid_override_set) {
        position_velocity_gains.position_kp_per_s = position_pid_override[0];
        position_velocity_gains.position_ki_per_s2 = position_pid_override[1];
        position_velocity_gains.position_kd = position_pid_override[2];
    }
    if (velocity_pid_override_set) {
        position_velocity_gains.velocity_kp_deg_per_cm_s = velocity_pid_override[0];
        position_velocity_gains.velocity_ki_deg_per_cm = velocity_pid_override[1];
        position_velocity_gains.velocity_kd_deg_s_per_cm_s = velocity_pid_override[2];
    }
    position_integral_cm_s = 0.0f;
    velocity_integral_deg = 0.0f;
    // The legacy PID remains disabled; the selected Task1 law is separate.
    setBallGains(0.0f, 0.0f, 0.0f);
    setBallFeedforwardSplit(profile.feedforward.positive, profile.feedforward.negative);

    setBallBrakePShortProfile(profile.brake.short_kp,
                              profile.brake.short_margin,
                              profile.brake.short_max,
                              profile.brake.short_dist);
    setBallBrakePLongProfile(profile.brake.long_kp,
                             profile.brake.long_margin,
                             profile.brake.long_max,
                             profile.brake.long_dist);
    setBallBrakePSpeed(profile.brake.speed_kp,
                       profile.brake.speed_target,
                       profile.brake.speed_max);
    setBallBrakePNegativeMax(profile.brake.negative_max);

    setBallTerminalBrakeGate(profile.terminal.brake_window,
                              profile.terminal.brake_velocity);
    if (task_control_mode == BallBeamTaskProfile::ControlMode::LegacyBrakePush) {
        setBallTerminalPushPositive(profile.terminal.push_positive_window,
                                    profile.terminal.push_positive_velocity,
                                    profile.terminal.push_positive_kp,
                                    2.0f);
        setBallTerminalPushNegative(profile.terminal.push_negative_window,
                                    profile.terminal.push_negative_velocity,
                                    profile.terminal.push_negative_kp,
                                    2.0f);
    } else {
        setBallTerminalPushPositive(0.0f, 0.0f, 0.0f, 0.0f);
        setBallTerminalPushNegative(0.0f, 0.0f, 0.0f, 0.0f);
    }

    setBallAngleLimit(profile.angle_command_limit_deg);
    setBallDeadband(profile.x_deadband_cm, profile.vx_deadband_cm_s);
    if (position_deadband_override_set) {
        x_deadband_cm = position_deadband_override_cm;
    }
    if (speed_limit_override_set) {
        position_velocity_gains.max_target_velocity_cm_s = speed_limit_override_cm_s;
    }
    setBallOuterLoopPeriod(profile.outer_loop_period_ms);
    setAngleRateLimit(profile.angle_rate_deg_per_s * kDegToRad);
}

bool BallBeamController::startTask(const TaskId task)
{
    const bool velocity_test = task == TaskId::VelocityStep;
    if (task != TaskId::Task1 && !velocity_test) {
        return false;
    }

    if (velocity_test && (std::fabs(velocity_test_target_cm_s) < 1.0f ||
        !has_estimated_ball_state || !isVisionFresh(HAL_GetTick()) ||
        std::fabs(output_ball_x_cm) > 1.0f ||
        std::fabs(output_ball_vx_cm_s) > 0.7f)) {
        return false;
    }

    applyTaskProfile(BallBeamTaskProfiles::Task1);
    velocity_test_command_cm_s = 0.0f;
    if (velocity_test) {
        velocity_test_command_cm_s = velocity_test_target_cm_s;
        velocity_test_start_ms = HAL_GetTick();
        velocity_test_has_previous_v = false;
        velocity_test_d_filtered_cm_s2 = 0.0f;
        applyBallTarget(0.0f);
        active_task = task;
        enableBalance();
        ball_sequence_stage = 10U; // fixed-speed segment
        return true;
    }
    task_start_pending = false;
    const float start_x_cm = has_estimated_ball_state ? output_ball_x_cm : ball_x_cm;
    const float start_vx_cm_s = has_estimated_ball_state ? output_ball_vx_cm_s : 0.0f;
    if ((std::fabs(start_x_cm) > 0.7f) || (std::fabs(start_vx_cm_s) > 0.8f)) {
        // This is a task restart, not a zero-point reset.  First return to the
        // already calibrated x=0, then start the normal Task1 sequence.
        task_start_pending = true;
        ball_sequence_active = false;
        ball_sequence_stage = 0U;
        applyBallTarget(0.0f);
    } else {
        startTask1SequenceWhenReady();
    }
    active_task = task;
    enableBalance();
    return true;
}

void BallBeamController::finishVelocityTest(const bool aborted)
{
    balance_enabled = false;
    active_task = TaskId::None;
    velocity_test_command_cm_s = 0.0f;
    velocity_test_start_ms = 0U;
    velocity_test_has_previous_v = false;
    velocity_test_d_filtered_cm_s2 = 0.0f;
    velocity_integral_deg = 0.0f;
    ball_sequence_stage = aborted ? 13U : 12U;
    last_angle_cmd_rad = balance_angle_rad;
    last_sent_angle_cmd_rad = balance_angle_rad;
    taskENTER_CRITICAL();
    if (has_last_control_input) {
        last_control_input.tick_ms = HAL_GetTick();
        last_control_input.target_v_cm_s = 0.0f;
    }
    taskEXIT_CRITICAL();
    Ctrl(CtrlType::AngleCtrl, balance_angle_rad);
}

void BallBeamController::startTask1SequenceWhenReady()
{
    task_start_pending = false;
    startBallSequence(BallBeamTaskProfiles::Task1.sequence.first_target,
                      BallBeamTaskProfiles::Task1.sequence.second_target,
                      BallBeamTaskProfiles::Task1.sequence.turn_window,
                      BallBeamTaskProfiles::Task1.sequence.turn_velocity);
}

void BallBeamController::initializeTask()
{
    disableBalance();
    setZeroPoint();
    setBalanceAngle(BallBeamTaskProfiles::Task1.balance_angle_deg * kDegToRad);
    Ctrl(CtrlType::AngleCtrl, getBalanceAngle());
}

void BallBeamController::stopTask()
{
    disableBalance();
}

void BallBeamController::setBallTarget(const float target_x_cm_)
{
    ball_sequence_active = false;
    ball_sequence_stage = 0U;
    applyBallTarget(target_x_cm_);
}

void BallBeamController::startPositionTarget(const float target_x_cm_)
{
    if (!std::isfinite(target_x_cm_) || std::fabs(target_x_cm_) > 10.0f) {
        return;
    }
    if (task_control_mode != BallBeamTaskProfile::ControlMode::PositionVelocity) {
        applyTaskProfile(BallBeamTaskProfiles::Task1);
    }
    setBallTarget(target_x_cm_);
    enableBalance();
}

void BallBeamController::startBallSequence(const float first_target_x_cm,
                                           const float second_target_x_cm,
                                           const float turn_window_cm,
                                           const float turn_vx_cm_s)
{
    ball_sequence_first_target_cm = first_target_x_cm;
    ball_sequence_second_target_cm = second_target_x_cm;
    if (std::isfinite(turn_window_cm)) {
        ball_sequence_turn_window_cm = std::max(0.0f, turn_window_cm);
    }
    if (std::isfinite(turn_vx_cm_s)) {
        ball_sequence_turn_vx_cm_s = std::max(0.0f, turn_vx_cm_s);
    }
    ball_sequence_active = true;
    ball_sequence_stage = 1U;
    applyBallTarget(ball_sequence_first_target_cm);
}

void BallBeamController::applyBallTarget(const float target_x_cm_)
{
    const float start_x_cm = has_estimated_ball_state ? output_ball_x_cm : ball_x_cm;
    target_start_x_cm = start_x_cm;
    target_move_dist_cm = std::fabs(target_x_cm_ - target_start_x_cm);
    const float target_delta_cm = target_x_cm_ - start_x_cm;
    if (std::fabs(target_delta_cm) > 0.01f) {
        target_motion_direction = (target_delta_cm > 0.0f) ? 1.0f : -1.0f;
    } else {
        target_motion_direction = 0.0f;
    }
    target_x_cm = target_x_cm_;
    updateEffectiveBrakePForMove();
    ball_error_integral_cm_s = 0.0f;
    position_integral_cm_s = 0.0f;
    velocity_integral_deg = 0.0f;
    last_error_cm = 0.0f;
    previous_error_cm = 0.0f;
    previous_previous_error_cm = 0.0f;
    has_incremental_pid_history = false;
    last_control_tick_ms = 0U;
    has_last_control_x = false;
    last_raw_control_dx_cm = 0.0f;
    last_control_dx_cm = 0.0f;
    brake_p_active = false;
    brake_p_active_direction = 0.0f;
    last_terminal_trim_deg = 0.0f;
    terminal_correction_latched = false;
    last_brake_p_offset_deg = 0.0f;
    last_brake_p_active = false;
    last_terminal_push_active = false;
    last_terminal_trim_active = false;
    last_terminal_brake_gate_active = false;
    last_stalled_before_terminal = false;
}

void BallBeamController::setBalanceAngle(const float angle_rad)
{
    if (!std::isfinite(angle_rad)) {
        return;
    }
    balance_angle_rad = angle_rad;
    angle_reference_rad = balance_angle_rad;
    last_angle_cmd_rad = angle_reference_rad;
    last_sent_angle_cmd_rad = last_angle_cmd_rad;
    ball_error_integral_cm_s = 0.0f;
    velocity_integral_deg = 0.0f;
    last_error_cm = 0.0f;
    previous_error_cm = 0.0f;
    previous_previous_error_cm = 0.0f;
    has_incremental_pid_history = false;
    last_control_tick_ms = 0U;
    has_last_control_x = false;
    last_raw_control_dx_cm = 0.0f;
    last_control_dx_cm = 0.0f;
    brake_p_active = false;
    brake_p_active_direction = 0.0f;
    target_motion_direction = 0.0f;
    ball_sequence_active = false;
    ball_sequence_stage = 0U;
    last_terminal_trim_deg = 0.0f;
    terminal_correction_latched = false;
    last_brake_p_offset_deg = 0.0f;
    last_brake_p_active = false;
    last_terminal_push_active = false;
    last_terminal_trim_active = false;
    last_terminal_brake_gate_active = false;
    last_stalled_before_terminal = false;
}

void BallBeamController::setBalanceTable(const float neg5_deg, const float zero_deg, const float pos5_deg)
{
    if (std::isfinite(neg5_deg)) {
        balance_angle_neg5_deg = neg5_deg;
    }
    if (std::isfinite(zero_deg)) {
        balance_angle_zero_deg = zero_deg;
    }
    if (std::isfinite(pos5_deg)) {
        balance_angle_pos5_deg = pos5_deg;
    }
    balance_angle_rad = getBalanceAngleForTarget(target_x_cm);
    if (!balance_enabled) {
        last_angle_cmd_rad = balance_angle_rad;
        last_sent_angle_cmd_rad = last_angle_cmd_rad;
    }
}

float BallBeamController::getBalanceAngleForTarget(const float target_x_cm_) const
{
    const float x = std::clamp(target_x_cm_, -5.0f, 5.0f);
    if (x <= 0.0f) {
        const float t = (x + 5.0f) / 5.0f;
        return (balance_angle_neg5_deg + (balance_angle_zero_deg - balance_angle_neg5_deg) * t) * kDegToRad;
    }

    const float t = x / 5.0f;
    return (balance_angle_zero_deg + (balance_angle_pos5_deg - balance_angle_zero_deg) * t) * kDegToRad;
}

void BallBeamController::setBallGains(const float kp_deg_per_cm_,
                                      const float ki_deg_per_cm_s_,
                                      const float kd_deg_per_cm_s_)
{
    if (std::isfinite(kp_deg_per_cm_)) {
        kp_deg_per_cm = kp_deg_per_cm_;
    }
    if (std::isfinite(ki_deg_per_cm_s_)) {
        ki_deg_per_cm_s = ki_deg_per_cm_s_;
    }
    if (std::isfinite(kd_deg_per_cm_s_)) {
        kd_deg_per_cm_s = kd_deg_per_cm_s_;
    }
    ball_error_integral_cm_s = 0.0f;
    last_error_cm = 0.0f;
    previous_error_cm = 0.0f;
    previous_previous_error_cm = 0.0f;
    has_incremental_pid_history = false;
}

void BallBeamController::setBallFeedforward(const float target_deg_per_cm)
{
    if (std::isfinite(target_deg_per_cm)) {
        target_feedforward_deg_per_cm = target_deg_per_cm;
        target_feedforward_pos_deg_per_cm = target_deg_per_cm;
        target_feedforward_neg_deg_per_cm = target_deg_per_cm;
    }
}

void BallBeamController::setBallFeedforwardSplit(const float pos_target_deg_per_cm,
                                                 const float neg_target_deg_per_cm)
{
    if (std::isfinite(pos_target_deg_per_cm)) {
        target_feedforward_pos_deg_per_cm = pos_target_deg_per_cm;
        target_feedforward_deg_per_cm = pos_target_deg_per_cm;
    }
    if (std::isfinite(neg_target_deg_per_cm)) {
        target_feedforward_neg_deg_per_cm = neg_target_deg_per_cm;
    }
}

void BallBeamController::setBallVisionWeight(const float far_error_cm,
                                             const float near_error_cm,
                                             const float min_weight)
{
    if (std::isfinite(far_error_cm) && std::isfinite(near_error_cm)) {
        const float far_cm = std::max(0.0f, far_error_cm);
        const float near_cm = std::max(0.0f, near_error_cm);
        vision_weight_far_error_cm = std::max(far_cm, near_cm + 0.01f);
        vision_weight_near_error_cm = std::min(near_cm, vision_weight_far_error_cm - 0.01f);
    }
    if (std::isfinite(min_weight)) {
        vision_weight_min = std::clamp(min_weight, 0.0f, 1.0f);
    }
}

void BallBeamController::setBallDWeight(const float far_error_cm,
                                        const float near_error_cm,
                                        const float min_weight)
{
    if (std::isfinite(far_error_cm) && std::isfinite(near_error_cm)) {
        const float far_cm = std::max(0.0f, far_error_cm);
        const float near_cm = std::max(0.0f, near_error_cm);
        d_weight_far_error_cm = std::max(far_cm, near_cm + 0.01f);
        d_weight_near_error_cm = std::min(near_cm, d_weight_far_error_cm - 0.01f);
    }
    if (std::isfinite(min_weight)) {
        d_weight_min = std::clamp(min_weight, 0.0f, 1.0f);
    }
}
float BallBeamController::calculateWeight(const float abs_error_cm,
                                          const float far_error_cm,
                                          const float near_error_cm,
                                          const float min_weight) const
{
    if (abs_error_cm <= near_error_cm) {
        return 1.0f;
    }
    if (abs_error_cm >= far_error_cm) {
        return min_weight;
    }

    const float span_cm = far_error_cm - near_error_cm;
    if (span_cm <= 0.01f) {
        return 1.0f;
    }
    const float t = (far_error_cm - abs_error_cm) / span_cm;
    return min_weight + (1.0f - min_weight) * std::clamp(t, 0.0f, 1.0f);
}

void BallBeamController::setBallBrakeP(const float kp_deg_per_cm,
                                       const float margin_cm,
                                       const float max_angle_deg)
{
    setBallBrakePShortProfile(kp_deg_per_cm, margin_cm, max_angle_deg, 5.0f);
    setBallBrakePLongProfile(kp_deg_per_cm, margin_cm, max_angle_deg, 5.0f);
}

void BallBeamController::setBallBrakePShortProfile(const float kp_deg_per_cm,
                                                   const float margin_cm,
                                                   const float max_angle_deg,
                                                   const float move_dist_cm)
{
    if (std::isfinite(kp_deg_per_cm)) {
        brake_p_short_kp_deg_per_cm = std::max(0.0f, kp_deg_per_cm);
    }
    if (std::isfinite(margin_cm)) {
        brake_p_short_margin_cm = std::max(0.0f, margin_cm);
    }
    if (std::isfinite(max_angle_deg)) {
        brake_p_short_max_angle_deg = std::max(0.0f, max_angle_deg);
    }
    if (std::isfinite(move_dist_cm)) {
        brake_p_short_dist_cm = std::max(0.1f, move_dist_cm);
    }
    updateEffectiveBrakePForMove();
}

void BallBeamController::setBallBrakePLongProfile(const float kp_deg_per_cm,
                                                  const float margin_cm,
                                                  const float max_angle_deg,
                                                  const float move_dist_cm)
{
    if (std::isfinite(kp_deg_per_cm)) {
        brake_p_long_kp_deg_per_cm = std::max(0.0f, kp_deg_per_cm);
    }
    if (std::isfinite(margin_cm)) {
        brake_p_long_margin_cm = std::max(0.0f, margin_cm);
    }
    if (std::isfinite(max_angle_deg)) {
        brake_p_long_max_angle_deg = std::max(0.0f, max_angle_deg);
    }
    if (std::isfinite(move_dist_cm)) {
        brake_p_long_dist_cm = std::max(0.1f, move_dist_cm);
    }
    updateEffectiveBrakePForMove();
}

void BallBeamController::setBallBrakePSpeed(const float kp_deg_per_cm_s,
                                            const float target_vx_cm_s,
                                            const float max_angle_deg)
{
    if (std::isfinite(kp_deg_per_cm_s)) {
        brake_p_speed_kp_deg_per_cm_s = std::max(0.0f, kp_deg_per_cm_s);
    }
    if (std::isfinite(target_vx_cm_s)) {
        brake_p_speed_target_vx_cm_s = std::max(0.0f, target_vx_cm_s);
    }
    if (std::isfinite(max_angle_deg)) {
        brake_p_speed_max_angle_deg = std::max(0.0f, max_angle_deg);
    }
}

void BallBeamController::setBallBrakePNegativeMax(const float max_angle_deg)
{
    if (std::isfinite(max_angle_deg)) {
        brake_p_negative_max_angle_override_deg = std::max(0.0f, max_angle_deg);
    }
}

void BallBeamController::updateEffectiveBrakePForMove()
{
    const float min_dist_cm = std::min(brake_p_short_dist_cm, brake_p_long_dist_cm);
    const float max_dist_cm = std::max(brake_p_short_dist_cm, brake_p_long_dist_cm);
    const bool short_is_min = brake_p_short_dist_cm <= brake_p_long_dist_cm;
    const float min_kp = short_is_min ? brake_p_short_kp_deg_per_cm : brake_p_long_kp_deg_per_cm;
    const float min_margin = short_is_min ? brake_p_short_margin_cm : brake_p_long_margin_cm;
    const float min_max = short_is_min ? brake_p_short_max_angle_deg : brake_p_long_max_angle_deg;
    const float max_kp = short_is_min ? brake_p_long_kp_deg_per_cm : brake_p_short_kp_deg_per_cm;
    const float max_margin = short_is_min ? brake_p_long_margin_cm : brake_p_short_margin_cm;
    const float max_max = short_is_min ? brake_p_long_max_angle_deg : brake_p_short_max_angle_deg;
    const float span_cm = std::max(0.1f, max_dist_cm - min_dist_cm);
    const float t = std::clamp((target_move_dist_cm - min_dist_cm) / span_cm, 0.0f, 1.0f);

    brake_p_kp_deg_per_cm = min_kp + (max_kp - min_kp) * t;
    brake_p_margin_cm = min_margin + (max_margin - min_margin) * t;
    brake_p_max_angle_deg = min_max + (max_max - min_max) * t;
}

void BallBeamController::setBallTerminalBrakeGate(const float x_window_cm,
                                                  const float vx_window_cm_s)
{
    if (std::isfinite(x_window_cm)) {
        terminal_brake_x_window_cm = std::max(0.0f, x_window_cm);
    }
    if (std::isfinite(vx_window_cm_s)) {
        terminal_brake_vx_window_cm_s = std::max(0.0f, vx_window_cm_s);
    }
}

void BallBeamController::setBallTerminalPush(const float window_cm,
                                             const float vx_window_cm_s,
                                             const float kp_deg_per_cm,
                                             const float max_angle_deg)
{
    if (std::isfinite(window_cm)) {
        terminal_push_window_cm = std::max(0.0f, window_cm);
    }
    if (std::isfinite(vx_window_cm_s)) {
        terminal_push_vx_window_cm_s = std::max(0.0f, vx_window_cm_s);
    }
    if (std::isfinite(kp_deg_per_cm)) {
        terminal_push_kp_deg_per_cm = std::max(0.0f, kp_deg_per_cm);
    }
    if (std::isfinite(max_angle_deg)) {
        terminal_push_max_angle_deg = std::max(0.0f, max_angle_deg);
    }
    setBallTerminalPushPositive(window_cm, vx_window_cm_s, kp_deg_per_cm, max_angle_deg);
    setBallTerminalPushNegative(window_cm, vx_window_cm_s, kp_deg_per_cm, max_angle_deg);
    last_terminal_trim_deg = 0.0f;
}

void BallBeamController::setBallTerminalPushPositive(const float window_cm,
                                                      const float vx_window_cm_s,
                                                      const float push_angle_deg,
                                                      const float unused_max_angle_deg)
{
    if (std::isfinite(window_cm)) {
        terminal_push_pos_window_cm = std::max(0.0f, window_cm);
    }
    if (std::isfinite(vx_window_cm_s)) {
        terminal_push_pos_vx_window_cm_s = std::max(0.0f, vx_window_cm_s);
    }
    (void)unused_max_angle_deg;
    if (std::isfinite(push_angle_deg)) {
        terminal_push_pos_kp_deg_per_cm = std::max(0.0f, push_angle_deg);
        terminal_push_pos_max_angle_deg = terminal_push_pos_kp_deg_per_cm;
    }
    last_terminal_trim_deg = 0.0f;
}

void BallBeamController::setBallTerminalPushNegative(const float window_cm,
                                                      const float vx_window_cm_s,
                                                      const float push_angle_deg,
                                                      const float unused_max_angle_deg)
{
    if (std::isfinite(window_cm)) {
        terminal_push_neg_window_cm = std::max(0.0f, window_cm);
    }
    if (std::isfinite(vx_window_cm_s)) {
        terminal_push_neg_vx_window_cm_s = std::max(0.0f, vx_window_cm_s);
    }
    (void)unused_max_angle_deg;
    if (std::isfinite(push_angle_deg)) {
        terminal_push_neg_kp_deg_per_cm = std::max(0.0f, push_angle_deg);
        terminal_push_neg_max_angle_deg = terminal_push_neg_kp_deg_per_cm;
    }
    last_terminal_trim_deg = 0.0f;
}

float BallBeamController::calculateVisionWeight(const float abs_error_cm) const
{
    return calculateWeight(abs_error_cm,
                           vision_weight_far_error_cm,
                           vision_weight_near_error_cm,
                           vision_weight_min);
}

float BallBeamController::calculateDWeight(const float abs_error_cm) const
{
    return calculateWeight(abs_error_cm,
                           d_weight_far_error_cm,
                           d_weight_near_error_cm,
                           d_weight_min);
}
void BallBeamController::setBallAngleLimit(const float max_delta_deg)
{
    if (std::isfinite(max_delta_deg)) {
        max_angle_delta_deg = std::max(0.0f, max_delta_deg);
    }
}

void BallBeamController::setBallDeadband(const float x_deadband_cm_, const float vx_deadband_cm_s_)
{
    if (std::isfinite(x_deadband_cm_)) {
        x_deadband_cm = std::max(0.0f, x_deadband_cm_);
    }
    if (std::isfinite(vx_deadband_cm_s_)) {
        vx_deadband_cm_s = std::max(0.0f, vx_deadband_cm_s_);
    }
}

void BallBeamController::setBallOuterLoopPeriod(const float period_ms)
{
    if (!std::isfinite(period_ms)) {
        return;
    }

    ball_outer_loop_period_ms =
        static_cast<uint32_t>(std::clamp(period_ms, 5.0f, 100.0f));
    last_control_tick_ms = 0U;
    has_last_control_x = false;
    last_raw_control_dx_cm = 0.0f;
    last_control_dx_cm = 0.0f;
}

void BallBeamController::setVelocityTestPid(const float kp, const float ki, const float kd)
{
    if (!std::isfinite(kp) || !std::isfinite(ki) || !std::isfinite(kd) ||
        kp < 0.0f || kp > 4.0f || ki < 0.0f || ki > 5.0f ||
        kd < 0.0f || kd > 0.2f) {
        return;
    }
    velocity_test_kp_deg_per_cm_s = kp;
    velocity_test_ki_deg_per_cm = ki;
    velocity_test_kd_deg_s_per_cm_s = kd;
    velocity_integral_deg = 0.0f;
    velocity_test_has_previous_v = false;
    velocity_test_d_filtered_cm_s2 = 0.0f;
}

void BallBeamController::setBallPositionPid(const float kp, const float ki, const float kd)
{
    if (!std::isfinite(kp) || !std::isfinite(ki) || !std::isfinite(kd) ||
        kp < 0.0f || ki < 0.0f || kd < 0.0f) {
        return;
    }
    position_pid_override[0] = kp;
    position_pid_override[1] = ki;
    position_pid_override[2] = kd;
    position_pid_override_set = true;
    position_velocity_gains.position_kp_per_s = kp;
    position_velocity_gains.position_ki_per_s2 = ki;
    position_velocity_gains.position_kd = kd;
    position_integral_cm_s = 0.0f;
}

void BallBeamController::setBallVelocityPid(const float kp, const float ki, const float kd)
{
    if (!std::isfinite(kp) || !std::isfinite(ki) || !std::isfinite(kd) ||
        kp < 0.0f || kp > 4.0f || ki < 0.0f || ki > 5.0f ||
        kd < 0.0f || kd > 0.2f) {
        return;
    }
    velocity_pid_override[0] = kp;
    velocity_pid_override[1] = ki;
    velocity_pid_override[2] = kd;
    velocity_pid_override_set = true;
    position_velocity_gains.velocity_kp_deg_per_cm_s = kp;
    position_velocity_gains.velocity_ki_deg_per_cm = ki;
    position_velocity_gains.velocity_kd_deg_s_per_cm_s = kd;
    setVelocityTestPid(kp, ki, kd);
}

bool BallBeamController::startVelocityTarget(const float target_v_cm_s)
{
    if (!std::isfinite(target_v_cm_s) || std::fabs(target_v_cm_s) < 1.0f ||
        std::fabs(target_v_cm_s) > 5.0f) {
        return false;
    }
    velocity_test_target_cm_s = target_v_cm_s;
    return startTask(TaskId::VelocityStep);
}

void BallBeamController::setBallPositionDeadband(const float deadband_cm)
{
    if (std::isfinite(deadband_cm)) {
        x_deadband_cm = std::max(0.0f, deadband_cm);
        position_deadband_override_cm = x_deadband_cm;
        position_deadband_override_set = true;
    }
}

void BallBeamController::setBallSpeedLimit(const float max_target_v_cm_s)
{
    if (std::isfinite(max_target_v_cm_s) && max_target_v_cm_s > 0.0f &&
        max_target_v_cm_s <= 12.0f) {
        position_velocity_gains.max_target_velocity_cm_s = max_target_v_cm_s;
        speed_limit_override_cm_s = max_target_v_cm_s;
        speed_limit_override_set = true;
    }
}

void BallBeamController::setVisionAb(const float alpha, const float beta)
{
    if (std::isfinite(alpha) && std::isfinite(beta) &&
        alpha >= 0.0f && alpha <= 1.0f && beta >= 0.0f && beta <= 1.0f) {
        vision_x_alpha = alpha;
        vision_vx_alpha = beta;
    }
}

void BallBeamController::setVisionActiveLimits(const float max_velocity_cm_s,
                                               const float max_x_step_cm)
{
    if (std::isfinite(max_velocity_cm_s) && max_velocity_cm_s > 0.0f &&
        std::isfinite(max_x_step_cm) && max_x_step_cm > 0.0f) {
        vision_max_velocity_cm_s = max_velocity_cm_s;
        vision_max_x_step_cm = max_x_step_cm;
    }
}

void BallBeamController::setVisionActivePrediction(const float predict_ms,
                                                   const float predict_step_cm)
{
    if (std::isfinite(predict_ms) && predict_ms >= 0.0f && predict_ms <= 80.0f &&
        std::isfinite(predict_step_cm) && predict_step_cm >= 0.0f) {
        vision_predict_hold_ms = static_cast<uint32_t>(predict_ms);
        vision_predict_max_step_cm = predict_step_cm;
    }
}

void BallBeamController::setVelocityTestConfig(const float kp, const float ki,
                                               const float kd, const float target_v_cm_s)
{
    if (!std::isfinite(target_v_cm_s) || std::fabs(target_v_cm_s) < 1.0f ||
        std::fabs(target_v_cm_s) > 5.0f) {
        return;
    }
    setBallVelocityPid(kp, ki, kd);
    velocity_test_target_cm_s = target_v_cm_s;
}

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

void BallBeamController::setVisionFilter(const float x_alpha,
                                         const float vx_alpha,
                                         const float dx_deadband_cm)
{
    if (std::isfinite(x_alpha)) {
        vision_x_alpha = std::clamp(x_alpha, 0.0f, 1.0f);
    }
    if (std::isfinite(vx_alpha)) {
        vision_vx_alpha = std::clamp(vx_alpha, 0.0f, 1.0f);
    }
    if (std::isfinite(dx_deadband_cm)) {
        vision_dx_deadband_cm = std::max(0.0f, dx_deadband_cm);
        vision_measurement_deadband_cm = std::max(0.0f, dx_deadband_cm);
    }
}

void BallBeamController::setVisionMeasurementDeadband(const float deadband_cm)
{
    if (std::isfinite(deadband_cm)) {
        vision_measurement_deadband_cm = std::max(0.0f, deadband_cm);
    }
}

void BallBeamController::setVisionFilterLimits(const float max_velocity_cm_s,
                                               const float interp_duration_ms,
                                               const float max_x_step_cm)
{
    if (std::isfinite(max_velocity_cm_s)) {
        vision_max_velocity_cm_s = std::max(0.0f, max_velocity_cm_s);
    }
    if (std::isfinite(interp_duration_ms)) {
        vision_interp_duration_ms = std::clamp(interp_duration_ms, 5.0f, 120.0f);
    }
    if (std::isfinite(max_x_step_cm)) {
        vision_max_x_step_cm = std::max(0.0f, max_x_step_cm);
    }
}

void BallBeamController::setVisionVelocity(const float window_points,
                                           const float min_dx_cm,
                                           const float reverse_limit)
{
    if (std::isfinite(window_points)) {
        const auto points = static_cast<uint8_t>(
            std::clamp(static_cast<int32_t>(std::lround(window_points)),
                       static_cast<int32_t>(2),
                       static_cast<int32_t>(kVisionVelocityHistoryCapacity)));
        vision_velocity_window_points = points;
    }
    if (std::isfinite(min_dx_cm)) {
        vision_velocity_min_dx_cm = std::max(0.0f, min_dx_cm);
    }
    if (std::isfinite(reverse_limit)) {
        const auto limit = static_cast<uint8_t>(
            std::clamp(static_cast<int32_t>(std::lround(reverse_limit)),
                       static_cast<int32_t>(0),
                       static_cast<int32_t>(kVisionVelocityHistoryCapacity - 2U)));
        vision_velocity_reverse_limit = limit;
    }
}

void BallBeamController::setVisionPrediction(const float sample_interval_ms,
                                             const float predict_ms,
                                             const float predict_step_cm)
{
    if (std::isfinite(sample_interval_ms)) {
        vision_velocity_sample_interval_ms =
            static_cast<uint32_t>(std::clamp(sample_interval_ms, 10.0f, 80.0f));
    }
    if (std::isfinite(predict_ms)) {
        vision_predict_hold_ms =
            static_cast<uint32_t>(std::clamp(predict_ms, 0.0f, 80.0f));
    }
    if (std::isfinite(predict_step_cm)) {
        vision_predict_max_step_cm = std::max(0.0f, predict_step_cm);
    }
}
void BallBeamController::setVisionAbCorrectionLimit(const float max_correction_step_cm)
{
    if (std::isfinite(max_correction_step_cm)) {
        vision_ab_max_correction_step_cm = std::max(0.0f, max_correction_step_cm);
    }
}

void BallBeamController::setAngleCommandDeadband(const float deadband_deg)
{
    if (std::isfinite(deadband_deg)) {
        angle_cmd_deadband_deg = std::max(0.0f, deadband_deg);
    }
}

void BallBeamController::setVisionTimeout(const uint32_t timeout_ms)
{
    vision_timeout_ms = timeout_ms;
}

void BallBeamController::updateVisionRaw(const VisionFrame_t& frame)
{
    if (frame.tracking_valid == 0U) {
        return;
    }

    vision_seq = frame.seq;
    vision_tracking_valid = true;
    last_vision_tick_ms = frame.rx_tick_ms;
    ball_x_cm = static_cast<float>(frame.ball_pos_001cm) * 0.01f;
    ball_vx_cm_s = static_cast<float>(frame.ball_vel_001cms) * 0.01f;
}

void BallBeamController::resetBallStateEstimator(const float x_cm, const uint32_t tick_ms)
{
    estimated_ball_x_cm = x_cm;
    filtered_ball_x_cm = x_cm;
    estimated_ball_vx_cm_s = 0.0f;
    raw_vision_diff_vx_cm_s = 0.0f;
    last_raw_vision_x_cm = x_cm;
    last_raw_vision_tick_ms = tick_ms;
    has_last_raw_vision_sample = true;
    last_measurement_x_cm = x_cm;
    interpolation_start_x_cm = x_cm;
    interpolation_target_x_cm = x_cm;
    interpolation_start_tick_ms = tick_ms;
    interpolation_duration_ms = static_cast<uint32_t>(vision_interp_duration_ms);
    output_ball_x_cm = x_cm;
    output_ball_vx_cm_s = 0.0f;
    has_estimated_ball_state = true;
    last_estimate_tick_ms = tick_ms;
    last_velocity_sample_tick_ms = tick_ms;
    resetVisionVelocityHistory(x_cm, tick_ms);
}

void BallBeamController::resetVisionVelocityHistory(const float x_cm, const uint32_t tick_ms)
{
    vision_velocity_history_head = 0U;
    vision_velocity_history_count = 0U;
    pushVisionVelocityPoint(x_cm, tick_ms);
}

void BallBeamController::pushVisionVelocityPoint(const float x_cm, const uint32_t tick_ms)
{
    vision_velocity_history[vision_velocity_history_head] = {x_cm, tick_ms};
    vision_velocity_history_head =
        static_cast<uint8_t>((vision_velocity_history_head + 1U) % kVisionVelocityHistoryCapacity);
    if (vision_velocity_history_count < kVisionVelocityHistoryCapacity) {
        ++vision_velocity_history_count;
    }
}

bool BallBeamController::estimateVisionVelocity(float *vx_cm_s) const
{
    if (vx_cm_s == nullptr) {
        return false;
    }

    const uint8_t points =
        std::min(vision_velocity_history_count, vision_velocity_window_points);
    if (points < 2U) {
        return false;
    }

    VisionVelocityPoint_t history[kVisionVelocityHistoryCapacity] = {};
    const uint8_t oldest =
        static_cast<uint8_t>((vision_velocity_history_head +
                              kVisionVelocityHistoryCapacity - points) %
                             kVisionVelocityHistoryCapacity);
    for (uint8_t i = 0U; i < points; ++i) {
        const uint8_t index = static_cast<uint8_t>((oldest + i) % kVisionVelocityHistoryCapacity);
        history[i] = vision_velocity_history[index];
    }

    const float total_dx_cm = history[points - 1U].x_cm - history[0U].x_cm;
    if (std::fabs(total_dx_cm) < vision_velocity_min_dx_cm) {
        return false;
    }

    const float direction = (total_dx_cm >= 0.0f) ? 1.0f : -1.0f;
    uint8_t reverse_count = 0U;
    for (uint8_t i = 1U; i < points; ++i) {
        const float step_dx_cm = history[i].x_cm - history[i - 1U].x_cm;
        if ((direction * step_dx_cm) < -vision_dx_deadband_cm) {
            ++reverse_count;
        }
    }
    if (reverse_count > vision_velocity_reverse_limit) {
        return false;
    }

    const uint32_t first_tick_ms = history[0U].tick_ms;
    float sum_t = 0.0f;
    float sum_x = 0.0f;
    float sum_tt = 0.0f;
    float sum_tx = 0.0f;
    for (uint8_t i = 0U; i < points; ++i) {
        const float t_s = static_cast<float>(history[i].tick_ms - first_tick_ms) * 0.001f;
        const float x_cm = history[i].x_cm;
        sum_t += t_s;
        sum_x += x_cm;
        sum_tt += t_s * t_s;
        sum_tx += t_s * x_cm;
    }

    const float n = static_cast<float>(points);
    const float denominator = n * sum_tt - sum_t * sum_t;
    if (denominator <= 1.0e-6f) {
        return false;
    }

    *vx_cm_s = std::clamp((n * sum_tx - sum_t * sum_x) / denominator,
                          -vision_max_velocity_cm_s,
                          vision_max_velocity_cm_s);
    return true;
}

void BallBeamController::updateVisionVelocityFromCleanPosition(const float clean_x_cm,
                                                               const uint32_t tick_ms)
{
    if ((tick_ms - last_velocity_sample_tick_ms) < vision_velocity_sample_interval_ms) {
        return;
    }

    pushVisionVelocityPoint(clean_x_cm, tick_ms);
    last_velocity_sample_tick_ms = tick_ms;

    float regression_vx_cm_s = 0.0f;
    if (estimateVisionVelocity(&regression_vx_cm_s)) {
        estimated_ball_vx_cm_s += vision_vx_alpha * (regression_vx_cm_s - estimated_ball_vx_cm_s);
    } else {
        estimated_ball_vx_cm_s *= vision_static_velocity_decay;
    }
    estimated_ball_vx_cm_s = std::clamp(estimated_ball_vx_cm_s,
                                        -vision_max_velocity_cm_s,
                                        vision_max_velocity_cm_s);
    if (std::fabs(estimated_ball_vx_cm_s) < 0.50f) {
        estimated_ball_vx_cm_s = 0.0f;
    }
}

void BallBeamController::updateRawVisionDiffVelocity(const float measured_x_cm,
                                                     const uint32_t tick_ms)
{
    if (!has_last_raw_vision_sample) {
        last_raw_vision_x_cm = measured_x_cm;
        last_raw_vision_tick_ms = tick_ms;
        has_last_raw_vision_sample = true;
        raw_vision_diff_vx_cm_s = 0.0f;
        return;
    }

    const uint32_t dt_ms = tick_ms - last_raw_vision_tick_ms;
    if (dt_ms >= kMinimumEstimatorDtMs) {
        const float dt_s = static_cast<float>(dt_ms) * 0.001f;
        raw_vision_diff_vx_cm_s = std::clamp((measured_x_cm - last_raw_vision_x_cm) / dt_s,
                                             -vision_max_velocity_cm_s,
                                             vision_max_velocity_cm_s);
        last_raw_vision_x_cm = measured_x_cm;
        last_raw_vision_tick_ms = tick_ms;
    }
}

void BallBeamController::predictBallStateTo(const uint32_t now_ms)
{
    if (!has_estimated_ball_state) {
        return;
    }

    const uint32_t elapsed_ms = now_ms - last_estimate_tick_ms;
    if (elapsed_ms < kMinimumEstimatorDtMs) {
        return;
    }

    const uint32_t predict_ms = std::min(elapsed_ms, vision_predict_hold_ms);
    const float predict_step_cm =
        std::clamp(estimated_ball_vx_cm_s * static_cast<float>(predict_ms) * 0.001f,
                   -vision_predict_max_step_cm,
                   vision_predict_max_step_cm);
    estimated_ball_x_cm += predict_step_cm;
    filtered_ball_x_cm = estimated_ball_x_cm;
    last_estimate_tick_ms = now_ms;
}

void BallBeamController::updateBallStateWithMeasurement(const float measured_x_cm, const uint32_t measurement_tick_ms, const uint32_t now_ms)
{
    const uint32_t previous_raw_tick_ms = last_raw_vision_tick_ms;
    const bool had_raw_sample = has_last_raw_vision_sample;
    updateRawVisionDiffVelocity(measured_x_cm, measurement_tick_ms);

    if (!has_estimated_ball_state) {
        resetBallStateEstimator(measured_x_cm, now_ms);
        return;
    }

    predictBallStateTo(now_ms);

    const float measurement_x_cm =
        (std::fabs(measured_x_cm - last_measurement_x_cm) < vision_measurement_deadband_cm)
            ? last_measurement_x_cm
            : measured_x_cm;
    const uint32_t raw_dt_ms = had_raw_sample ? (measurement_tick_ms - previous_raw_tick_ms) : kMinimumEstimatorDtMs;
    const uint32_t measurement_dt_ms = std::max<uint32_t>(raw_dt_ms, kMinimumEstimatorDtMs);
    const float dt_s = static_cast<float>(measurement_dt_ms) * 0.001f;
    const float residual_cm = std::clamp(measurement_x_cm - estimated_ball_x_cm,
                                         -vision_max_x_step_cm,
                                         vision_max_x_step_cm);

    estimated_ball_x_cm += vision_x_alpha * residual_cm;
    estimated_ball_vx_cm_s += vision_vx_alpha * residual_cm / dt_s;
    estimated_ball_vx_cm_s = std::clamp(estimated_ball_vx_cm_s,
                                        -vision_max_velocity_cm_s,
                                        vision_max_velocity_cm_s);

    filtered_ball_x_cm = estimated_ball_x_cm;
    last_measurement_x_cm = measurement_x_cm;
    last_estimate_tick_ms = now_ms;
}

float BallBeamController::calculateInterpolatedX(const uint32_t now_ms,
                                                 const bool include_prediction) const
{
    (void)now_ms;
    (void)include_prediction;
    return estimated_ball_x_cm;
}

void BallBeamController::fillPredictedBallState(const uint32_t now_ms, BallStateEstimate_t *state) const
{
    if (state == nullptr) {
        return;
    }

    state->raw_x_cm = ball_x_cm;
    state->raw_vx_cm_s = raw_vision_diff_vx_cm_s;
    state->filtered_x_cm = filtered_ball_x_cm;
    state->x_cm = calculateInterpolatedX(now_ms, true);
    state->vx_cm_s = estimated_ball_vx_cm_s;
    state->valid = 1U;
    state->vision_seq = vision_seq;
    state->update_tick_ms = now_ms;
    state->vision_age_ms = (last_vision_tick_ms == 0U) ? 9999U : (now_ms - last_vision_tick_ms);
}

bool BallBeamController::updateBallStateEstimator(const uint32_t now_ms, BallStateEstimate_t *state)
{
    if (state == nullptr) {
        return false;
    }

    state->valid = 0U;
    state->raw_x_cm = ball_x_cm;
    state->raw_vx_cm_s = raw_vision_diff_vx_cm_s;
    state->filtered_x_cm = filtered_ball_x_cm;
    state->x_cm = estimated_ball_x_cm;
    state->vx_cm_s = estimated_ball_vx_cm_s;
    state->vision_seq = vision_seq;
    state->update_tick_ms = now_ms;
    state->vision_age_ms = (last_vision_tick_ms == 0U) ? 9999U : (now_ms - last_vision_tick_ms);

    if (!isVisionFresh(now_ms)) {
        has_estimated_vision_seq = false;
        has_estimated_ball_state = false;
        estimated_ball_vx_cm_s = 0.0f;
        output_ball_vx_cm_s = 0.0f;
        raw_vision_diff_vx_cm_s = 0.0f;
        return false;
    }

    if (has_estimated_vision_seq && (vision_seq == estimated_vision_seq)) {
        if (!has_estimated_ball_state) {
            return false;
        }
        predictBallStateTo(now_ms);
    } else {
        estimated_vision_seq = vision_seq;
        has_estimated_vision_seq = true;
        updateBallStateWithMeasurement(ball_x_cm, last_vision_tick_ms, now_ms);
    }

    fillPredictedBallState(now_ms, state);
    output_ball_x_cm = state->x_cm;
    output_ball_vx_cm_s = state->vx_cm_s;
    return true;
}

void BallBeamController::updateVision(const VisionFrame_t& frame)
{
    updateVisionRaw(frame);
}

bool BallBeamController::isVisionFresh(const uint32_t now_ms) const
{
    return vision_tracking_valid && ((now_ms - last_vision_tick_ms) <= vision_timeout_ms);
}

void BallBeamController::Balance_ISR(const uint32_t now_ms)
{
    BallStateEstimate_t state = {};
    if (!updateBallStateEstimator(now_ms, &state)) {
        return;
    }
    updateBalanceControl(state, now_ms);
}

void BallBeamController::updateBalanceControl(const BallStateEstimate_t& state, const uint32_t now_ms)
{
    if (!balance_enabled) {
        return;
    }

    if (state.valid == 0U) {
        if (velocity_test_command_cm_s != 0.0f) {
            finishVelocityTest(true);
        }
        velocity_integral_deg = 0.0f;
        has_control_vision_seq = false;
        has_last_control_x = false;
        last_raw_control_dx_cm = 0.0f;
        last_control_dx_cm = 0.0f;
        last_control_tick_ms = 0U;
        last_brake_p_offset_deg = 0.0f;
        terminal_correction_latched = false;
        last_brake_p_active = false;
        last_terminal_push_active = false;
        last_terminal_trim_active = false;
        last_terminal_brake_gate_active = false;
        last_stalled_before_terminal = false;
        return;
    }

    if ((last_control_tick_ms != 0U) &&
        ((now_ms - last_control_tick_ms) < ball_outer_loop_period_ms)) {
        return;
    }

    const bool velocity_test = velocity_test_command_cm_s != 0.0f;
    if (velocity_test) {
        const uint32_t elapsed_ms = now_ms - velocity_test_start_ms;
        if (std::fabs(state.vx_cm_s) >= 12.0f || elapsed_ms >= 8000U) {
            finishVelocityTest(true);
            return;
        }
        if (std::fabs(state.x_cm) >= 6.0f) {
            finishVelocityTest(state.x_cm * velocity_test_command_cm_s < 0.0f);
            return;
        }
    }

    if (task_start_pending &&
        (std::fabs(state.x_cm) <= 0.7f) &&
        (std::fabs(state.vx_cm_s) <= 0.8f)) {
        startTask1SequenceWhenReady();
    }

    // Give BPUSH one or more control cycles before a device sequence changes
    // target.  Without this guard, a stopped ball at e.g. +5.42 cm satisfies
    // the loose turn window and the target changes to -5 immediately, so the
    // +5 BPUSH path never gets a chance to correct the residual error.
    const float sequence_target_cm = (ball_sequence_stage == 1U)
                                         ? ball_sequence_first_target_cm
                                         : ball_sequence_second_target_cm;
    const float sequence_error_cm = sequence_target_cm - state.x_cm;
    const bool sequence_positive_move = target_motion_direction >= 0.0f;
    const float sequence_push_window_cm = sequence_positive_move
                                              ? terminal_push_pos_window_cm
                                              : terminal_push_neg_window_cm;
    const float sequence_push_vx_window_cm_s = sequence_positive_move
                                                   ? terminal_push_pos_vx_window_cm_s
                                                   : terminal_push_neg_vx_window_cm_s;
    const float sequence_push_kp_deg_per_cm = sequence_positive_move
                                                  ? terminal_push_pos_kp_deg_per_cm
                                                  : terminal_push_neg_kp_deg_per_cm;
    const float sequence_push_max_angle_deg = sequence_positive_move
                                                  ? terminal_push_pos_max_angle_deg
                                                  : terminal_push_neg_max_angle_deg;
    const bool sequence_push_pending =
        (sequence_push_window_cm > 0.0f) &&
        (sequence_push_kp_deg_per_cm > 0.0f) &&
        (sequence_push_max_angle_deg > 0.0f) &&
        (std::fabs(sequence_error_cm) > terminal_trim_deadband_cm) &&
        (std::fabs(sequence_error_cm) <= sequence_push_window_cm) &&
        (std::fabs(state.vx_cm_s) <= sequence_push_vx_window_cm_s);

    if (ball_sequence_active && (ball_sequence_stage == 1U) &&
        (std::fabs(state.x_cm - ball_sequence_first_target_cm) <= ball_sequence_turn_window_cm) &&
        (std::fabs(state.vx_cm_s) <= ball_sequence_turn_vx_cm_s) &&
        !sequence_push_pending) {
        ball_sequence_stage = 2U;
        applyBallTarget(ball_sequence_second_target_cm);
    } else if (ball_sequence_active && (ball_sequence_stage == 2U) &&
               (std::fabs(state.x_cm - ball_sequence_second_target_cm) <= ball_sequence_turn_window_cm) &&
               (std::fabs(state.vx_cm_s) <= ball_sequence_turn_vx_cm_s) &&
               !sequence_push_pending) {
        ball_sequence_stage = 0U;
        ball_sequence_active = false;
    }

    const float dt_s = (last_control_tick_ms == 0U)
                           ? static_cast<float>(ball_outer_loop_period_ms) * 0.001f
                           : static_cast<float>(now_ms - last_control_tick_ms) * 0.001f;
    last_control_tick_ms = now_ms;

    const float control_dx_cm = has_last_control_x ? (state.x_cm - last_control_x_cm) : 0.0f;
    last_raw_control_dx_cm = control_dx_cm;
    has_last_control_x = true;
    last_control_x_cm = state.x_cm;

    const float raw_error_cm = target_x_cm - state.x_cm;
    float error_cm = raw_error_cm;
    float d_x_cm = control_dx_cm;

    if (std::fabs(error_cm) < x_deadband_cm) {
        error_cm = 0.0f;
    }
    if (std::fabs(d_x_cm) < (vx_deadband_cm_s * dt_s)) {
        d_x_cm = 0.0f;
    }
    last_control_dx_cm = d_x_cm;

    if (task_control_mode == BallBeamTaskProfile::ControlMode::PositionVelocity) {
        if (velocity_test) {
            const float speed_error_cm_s = velocity_test_command_cm_s - state.vx_cm_s;
            const float p_deg = velocity_test_kp_deg_per_cm_s * speed_error_cm_s;
            const float measured_accel_cm_s2 = (velocity_test_has_previous_v && dt_s > 0.0f)
                ? (state.vx_cm_s - velocity_test_previous_v_cm_s) / dt_s : 0.0f;
            velocity_test_previous_v_cm_s = state.vx_cm_s;
            velocity_test_has_previous_v = true;
            velocity_test_d_filtered_cm_s2 =
                0.75f * velocity_test_d_filtered_cm_s2 + 0.25f * measured_accel_cm_s2;
            const float d_deg = -velocity_test_kd_deg_s_per_cm_s *
                velocity_test_d_filtered_cm_s2;
            const float candidate_i_deg = std::clamp(
                velocity_integral_deg + velocity_test_ki_deg_per_cm *
                    speed_error_cm_s * dt_s,
                -2.5f, 2.5f);
            const float candidate_feedback_deg = p_deg + candidate_i_deg + d_deg;
            if ((candidate_feedback_deg <= 7.0f || speed_error_cm_s < 0.0f) &&
                (candidate_feedback_deg >= -7.0f || speed_error_cm_s > 0.0f)) {
                velocity_integral_deg = candidate_i_deg;
            }
            const float feedback_deg = std::clamp(
                p_deg + velocity_integral_deg + d_deg, -7.0f, 7.0f);
            last_angle_cmd_rad = std::clamp(
                angle_reference_rad + feedback_deg * kDegToRad,
                angle_reference_rad - max_angle_delta_deg * kDegToRad,
                angle_reference_rad + max_angle_delta_deg * kDegToRad);
            last_error_cm = 0.0f;
            last_brake_p_offset_deg = 0.0f;
            last_terminal_trim_deg = 0.0f;
            last_brake_p_active = false;
            last_terminal_push_active = false;
            last_terminal_trim_active = false;
            last_terminal_brake_gate_active = false;
            last_stalled_before_terminal = false;
            taskENTER_CRITICAL();
            last_control_input = {now_ms, state.x_cm, state.vx_cm_s,
                                  velocity_test_command_cm_s};
            has_last_control_input = true;
            taskEXIT_CRITICAL();
            if (std::fabs(last_angle_cmd_rad - last_sent_angle_cmd_rad) >=
                angle_cmd_deadband_deg * kDegToRad) {
                last_sent_angle_cmd_rad = last_angle_cmd_rad;
                Ctrl(CtrlType::AngleCtrl, last_sent_angle_cmd_rad);
            }
            return;
        }
        // Outer position loop asks for a bounded speed; inner speed loop
        // converts speed error into a bounded angle correction.  Use the
        // estimator velocity already supplied to this 20 ms control update.
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
        const float target_velocity_cm_s = std::clamp(
            position_p_cm_s + position_d_cm_s +
                gains.position_ki_per_s2 * position_integral_cm_s,
            -gains.max_target_velocity_cm_s,
            gains.max_target_velocity_cm_s);
        const float velocity_error_cm_s = target_velocity_cm_s - state.vx_cm_s;
        const float measured_accel_cm_s2 = (velocity_test_has_previous_v && dt_s > 0.0f)
            ? (state.vx_cm_s - velocity_test_previous_v_cm_s) / dt_s : 0.0f;
        velocity_test_previous_v_cm_s = state.vx_cm_s;
        velocity_test_has_previous_v = true;
        velocity_test_d_filtered_cm_s2 =
            0.75f * velocity_test_d_filtered_cm_s2 + 0.25f * measured_accel_cm_s2;
        const float velocity_d_deg = -gains.velocity_kd_deg_s_per_cm_s *
            velocity_test_d_filtered_cm_s2;
        const float feedforward_deg = target_x_cm *
            ((target_x_cm >= 0.0f) ? target_feedforward_pos_deg_per_cm
                                   : target_feedforward_neg_deg_per_cm);
        const float abs_error_cm = std::fabs(error_cm);
        const float abs_speed_cm_s = std::fabs(state.vx_cm_s);
        const float error_weight = std::clamp(
            (gains.integral_zero_error_cm - abs_error_cm) /
                std::max(0.001f, gains.integral_zero_error_cm - gains.integral_full_error_cm),
            0.0f, 1.0f);
        const float speed_weight = std::clamp(
            (gains.integral_zero_speed_cm_s - abs_speed_cm_s) /
                std::max(0.001f, gains.integral_zero_speed_cm_s - gains.integral_full_speed_cm_s),
            0.0f, 1.0f);
        const float integral_weight = (error_cm != 0.0f &&
            (!gains.integral_negative_target_only || target_x_cm < 0.0f))
                ? error_weight * speed_weight : 0.0f;
        if (integral_weight == 0.0f) {
            velocity_integral_deg *= std::clamp(
                1.0f - gains.integral_leak_per_s * dt_s, 0.0f, 1.0f);
        }
        const float candidate_integral_deg = std::clamp(
            velocity_integral_deg + gains.velocity_ki_deg_per_cm * velocity_error_cm_s *
                integral_weight * dt_s,
            -gains.max_velocity_integral_deg,
            gains.max_velocity_integral_deg);
        const float candidate_feedback_deg =
            gains.velocity_kp_deg_per_cm_s * velocity_error_cm_s +
            candidate_integral_deg + velocity_d_deg;
        const float candidate_total_deg = feedforward_deg + candidate_feedback_deg;
        // Do not integrate further in the direction of either angle limit.
        const bool pushing_upper_limit = (velocity_error_cm_s > 0.0f) &&
            ((candidate_feedback_deg > gains.max_feedback_angle_deg) ||
             (candidate_total_deg > max_angle_delta_deg));
        const bool pushing_lower_limit = (velocity_error_cm_s < 0.0f) &&
            ((candidate_feedback_deg < -gains.max_feedback_angle_deg) ||
             (candidate_total_deg < -max_angle_delta_deg));
        if (!pushing_upper_limit && !pushing_lower_limit) {
            velocity_integral_deg = candidate_integral_deg;
        }
        const float feedback_deg = std::clamp(
            gains.velocity_kp_deg_per_cm_s * velocity_error_cm_s +
                velocity_integral_deg + velocity_d_deg,
            -gains.max_feedback_angle_deg,
            gains.max_feedback_angle_deg);
        last_angle_cmd_rad = std::clamp(
            angle_reference_rad + (feedforward_deg + feedback_deg) * kDegToRad,
            angle_reference_rad - max_angle_delta_deg * kDegToRad,
            angle_reference_rad + max_angle_delta_deg * kDegToRad);
        last_error_cm = error_cm;
        last_brake_p_offset_deg = 0.0f;
        last_terminal_trim_deg = 0.0f;
        last_brake_p_active = false;
        last_terminal_push_active = false;
        last_terminal_trim_active = false;
        last_terminal_brake_gate_active = false;
        last_stalled_before_terminal = false;
        taskENTER_CRITICAL();
        last_control_input = {now_ms, state.x_cm, state.vx_cm_s, target_velocity_cm_s};
        has_last_control_input = true;
        taskEXIT_CRITICAL();
        if (std::fabs(last_angle_cmd_rad - last_sent_angle_cmd_rad) >=
            angle_cmd_deadband_deg * kDegToRad) {
            last_sent_angle_cmd_rad = last_angle_cmd_rad;
            Ctrl(CtrlType::AngleCtrl, last_sent_angle_cmd_rad);
        }
        return;
    }

}


















