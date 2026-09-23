#include "BallBeamController.h"

#include <algorithm>
#include <cmath>

namespace {

constexpr uint32_t kMinimumEstimatorDtMs = 5U;

} // namespace

void BallBeamController::enableBalance()
{
    balance_enabled = true;
    has_control_vision_seq = false;
    has_last_control_x = false;
    last_raw_control_dx_cm = 0.0f;
    last_control_dx_cm = 0.0f;
    ball_error_integral_cm_s = 0.0f;
    last_error_cm = 0.0f;
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
    balance_enabled = false;
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
}

void BallBeamController::applyTaskProfile(const BallBeamTaskProfile& profile)
{
    setBalanceAngle(profile.balance_angle_deg * kDegToRad);
    // Task1 uses feedforward + BBP/BPUSH only; keep the legacy ball PID disabled.
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
    setBallTerminalPushPositive(profile.terminal.push_positive_window,
                                profile.terminal.push_positive_velocity,
                                profile.terminal.push_positive_kp,
                                2.0f);
    setBallTerminalPushNegative(profile.terminal.push_negative_window,
                                profile.terminal.push_negative_velocity,
                                profile.terminal.push_negative_kp,
                                2.0f);

    setBallAngleLimit(profile.angle_command_limit_deg);
    setBallDeadband(profile.x_deadband_cm, profile.vx_deadband_cm_s);
    setBallOuterLoopPeriod(profile.outer_loop_period_ms);
    setAngleRateLimit(profile.angle_rate_deg_per_s * kDegToRad);
}

bool BallBeamController::startTask(const TaskId task)
{
    if (task != TaskId::Task1) {
        return false;
    }

    applyTaskProfile(BallBeamTaskProfiles::Task1);
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
    setBalanceAngle(22.0f * kDegToRad);
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

    if (dt_s > 0.0f) {
        ball_error_integral_cm_s += error_cm * dt_s;
        ball_error_integral_cm_s = std::clamp(ball_error_integral_cm_s,
                                              -integral_limit_cm_s,
                                              integral_limit_cm_s);
    }

    last_error_cm = error_cm;
    const float min_angle_rad = angle_reference_rad - max_angle_delta_deg * kDegToRad;
    const float max_angle_rad = angle_reference_rad + max_angle_delta_deg * kDegToRad;
    const float control_velocity_cm_s = (dt_s > 0.0f) ? (d_x_cm / dt_s) : 0.0f;
    const float velocity_cm_s = state.vx_cm_s;
    const float abs_error_cm = std::fabs(error_cm);
    const float abs_raw_error_cm = std::fabs(raw_error_cm);
    const float position_weight = calculateVisionWeight(abs_error_cm);
    const float d_weight = calculateDWeight(abs_error_cm);
    const float position_offset_deg = kp_deg_per_cm * error_cm +
                                      ki_deg_per_cm_s * ball_error_integral_cm_s;
    const float brake_offset_deg = -kd_deg_per_cm_s * control_velocity_cm_s;
    const float direction = (target_motion_direction != 0.0f)
                                ? target_motion_direction
                                : ((raw_error_cm >= 0.0f) ? 1.0f : -1.0f);
    const bool before_target_in_motion_direction = (raw_error_cm * direction) > 0.0f;
    const float v_toward_target_cm_s = velocity_cm_s * direction;
    const bool past_target_in_motion_direction = (raw_error_cm * direction) < 0.0f;
    const bool moving_away_after_target =
        past_target_in_motion_direction && (v_toward_target_cm_s > vx_deadband_cm_s);
    const bool terminal_brake_gate =
        (std::fabs(raw_error_cm) <= terminal_brake_x_window_cm) &&
        (std::fabs(velocity_cm_s) <= terminal_brake_vx_window_cm_s);
    // The terminal contract is intentionally simple: BPUSH is the only
    // correction path once the ball has nearly stopped.  The historical
    // BTRIM controller has been removed.
    const bool positive_move = direction >= 0.0f;
    const float push_window_cm = positive_move ? terminal_push_pos_window_cm : terminal_push_neg_window_cm;
    const float push_vx_window_cm_s = positive_move ? terminal_push_pos_vx_window_cm_s : terminal_push_neg_vx_window_cm_s;
    const float push_delta_angle_deg = positive_move ? terminal_push_pos_kp_deg_per_cm : terminal_push_neg_kp_deg_per_cm;
    const bool bpush_configured = (push_window_cm > 0.0f) &&
                                  (push_delta_angle_deg > 0.0f);
    const float terminal_correction_window_cm = bpush_configured ? push_window_cm : 0.0f;
    const float terminal_correction_vx_window_cm_s = bpush_configured ? push_vx_window_cm_s : 0.0f;
    if ((terminal_correction_window_cm <= 0.0f) ||
        (abs_raw_error_cm > (terminal_correction_window_cm + 0.35f))) {
        terminal_correction_latched = false;
    } else if ((abs_raw_error_cm <= terminal_correction_window_cm) &&
               (std::fabs(velocity_cm_s) <= terminal_correction_vx_window_cm_s)) {
        terminal_correction_latched = true;
    }
    const bool terminal_correction_gate =
        (terminal_correction_window_cm > 0.0f) &&
        (std::fabs(raw_error_cm) <= terminal_correction_window_cm) &&
        ((std::fabs(velocity_cm_s) <= terminal_correction_vx_window_cm_s) ||
         terminal_correction_latched);
    const float brake_target_x_cm = target_x_cm - brake_p_margin_cm * direction;
    const float brake_region_cm = (state.x_cm - brake_target_x_cm) * direction;
    const bool stalled_before_terminal =
        (std::fabs(raw_error_cm) > terminal_brake_x_window_cm) &&
        (std::fabs(velocity_cm_s) <= vx_deadband_cm_s) &&
        (brake_region_cm > 0.0f);
    float brake_p_offset_deg = 0.0f;

    if (brake_p_active && (brake_p_active_direction != direction)) {
        brake_p_active = false;
        brake_p_active_direction = 0.0f;
    }

    if ((brake_p_kp_deg_per_cm <= 0.0f) ||
        (target_motion_direction == 0.0f) ||
        (!(before_target_in_motion_direction || moving_away_after_target)) ||
        terminal_brake_gate ||
        terminal_correction_gate ||
        stalled_before_terminal ||
        (brake_region_cm <= 0.0f)) {
        brake_p_active = false;
        brake_p_active_direction = 0.0f;
    } else if (v_toward_target_cm_s > vx_deadband_cm_s) {
        brake_p_active = true;
        brake_p_active_direction = direction;
    }

    if (brake_p_active) {
        const float distance_brake_deg = brake_p_kp_deg_per_cm * brake_region_cm;
        const float speed_excess_cm_s = std::max(0.0f,
                                                 v_toward_target_cm_s - brake_p_speed_target_vx_cm_s);
        const float speed_brake_deg = std::min(brake_p_speed_kp_deg_per_cm_s * speed_excess_cm_s,
                                               brake_p_speed_max_angle_deg);
        const float direction_max_angle_deg =
            (direction < 0.0f && brake_p_negative_max_angle_override_deg >= 0.0f)
                ? brake_p_negative_max_angle_override_deg
                : brake_p_max_angle_deg;
        brake_p_offset_deg = -direction * std::min(distance_brake_deg + speed_brake_deg,
                                                   direction_max_angle_deg);
    }

    float target_terminal_trim_deg = 0.0f;
    // bpush is symmetric around the target.  It therefore handles both
    // undershoot (raw_error > 0 for a positive target) and mild overshoot
    // without a second sign/opposite-direction controller.
    const bool terminal_push_recovery_allowed =
        bpush_configured &&
        (!brake_p_active) &&
        (abs_raw_error_cm <= push_window_cm) &&
        (abs_raw_error_cm > terminal_trim_deadband_cm) &&
        (std::fabs(velocity_cm_s) <= push_vx_window_cm_s);
    if (terminal_push_recovery_allowed) {
        const float error_sign = (raw_error_cm >= 0.0f) ? 1.0f : -1.0f;
        // BPUSH angle sign follows the positional error directly.  The
        // measured motor/beam response has one global angle polarity; it
        // does not need an extra target-motion-direction factor.  Keeping
        // that factor would reverse the push sign for the negative target.
        target_terminal_trim_deg = error_sign * push_delta_angle_deg;
    }
    last_brake_p_active = brake_p_active;
    last_brake_p_offset_deg = brake_p_offset_deg;
    last_terminal_push_active = terminal_push_recovery_allowed;
    // Kept false for telemetry compatibility; BTRIM no longer exists.
    last_terminal_trim_active = false;
    last_terminal_brake_gate_active = terminal_brake_gate;
    last_stalled_before_terminal = stalled_before_terminal;

    if (terminal_push_recovery_allowed) {
        // BPUSH is a friction-breakaway impulse.  Apply the configured
        // fixed offset immediately; do not turn it into a slow trim loop.
        last_terminal_trim_deg = target_terminal_trim_deg;
    } else if (bpush_configured) {
        // Once the ball moves or leaves the recovery window, hand control
        // back to BBP immediately; do not leave a stale push offset behind.
        last_terminal_trim_deg = 0.0f;
    } else {
        last_terminal_trim_deg = 0.0f;
    }

    const float target_feedforward_eff_deg_per_cm =
        (target_x_cm >= 0.0f) ? target_feedforward_pos_deg_per_cm : target_feedforward_neg_deg_per_cm;
    const float angle_offset_deg = target_feedforward_eff_deg_per_cm * target_x_cm +
                                   position_weight * position_offset_deg +
                                   d_weight * brake_offset_deg +
                                   brake_p_offset_deg +
                                   last_terminal_trim_deg;

    last_angle_cmd_rad = std::clamp(angle_reference_rad + angle_offset_deg * kDegToRad,
                                    min_angle_rad,
                                    max_angle_rad);
    previous_previous_error_cm = previous_error_cm;
    previous_error_cm = error_cm;
    has_incremental_pid_history = true;
    const float angle_cmd_delta_rad = last_angle_cmd_rad - last_sent_angle_cmd_rad;
    if (std::fabs(angle_cmd_delta_rad) < (angle_cmd_deadband_deg * kDegToRad)) {
        return;
    }

    last_sent_angle_cmd_rad = last_angle_cmd_rad;
    Ctrl(CtrlType::AngleCtrl, last_sent_angle_cmd_rad);
}


















