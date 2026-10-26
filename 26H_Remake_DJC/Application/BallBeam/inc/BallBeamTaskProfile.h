#ifndef BALL_BEAM_TASK_PROFILE_H
#define BALL_BEAM_TASK_PROFILE_H

#include <stdint.h>

// 闭环需要的参数，不包含任务编号、目标序列或启动条件。
struct BallBeamControlConfig {

    struct PositionVelocity {
        float position_kp_per_s;
        float position_ki_per_s2;
        float position_kd;
        float max_target_velocity_cm_s;
        float velocity_kp_deg_per_cm_s;
        float velocity_ki_deg_per_cm;
        float velocity_kd_deg_s_per_cm_s;
        float max_velocity_integral_deg;
        float max_feedback_angle_deg;
        float integral_full_error_cm;
        float integral_zero_error_cm;
        float integral_full_speed_cm_s;
        float integral_zero_speed_cm_s;
        float integral_leak_per_s;
        bool integral_negative_target_only;
    } position_velocity;

    struct Feedforward {
        float positive;
        float negative;
    } feedforward;

    float balance_angle_deg;
    float angle_rate_deg_per_s;
    float angle_command_limit_deg;
    float x_deadband_cm;
    float outer_loop_period_ms;
};

struct BallBeamTaskProfile {
    BallBeamControlConfig control;
    struct Sequence {
        float first_target;
        float second_target;
        float turn_window;
        float turn_velocity;
    } sequence;
};

namespace BallBeamTaskProfiles {

inline constexpr BallBeamTaskProfile Task1{
    .control = {
        .position_velocity = {
            .position_kp_per_s = 1.2f,
            .position_ki_per_s2 = 0.0f,
            .position_kd = 0.0f,
            .max_target_velocity_cm_s = 6.0f,
            .velocity_kp_deg_per_cm_s = 0.5f,
            .velocity_ki_deg_per_cm = 1.2f,
            .velocity_kd_deg_s_per_cm_s = 0.0f,
            .max_velocity_integral_deg = 2.5f,
            .max_feedback_angle_deg = 7.0f,
            .integral_full_error_cm = 2.0f,
            .integral_zero_error_cm = 4.0f,
            .integral_full_speed_cm_s = 1.0f,
            .integral_zero_speed_cm_s = 4.0f,
            .integral_leak_per_s = 4.0f,
            .integral_negative_target_only = true,
        },
        .feedforward = {.positive = 0.9f, .negative = 0.45f},
        .balance_angle_deg = 21.0f,
        .angle_rate_deg_per_s = 0.0f,
        .angle_command_limit_deg = 8.0f,
        .x_deadband_cm = 0.25f,
        .outer_loop_period_ms = 20.0f,
    },
    .sequence = {
        .first_target = 5.0f,
        .second_target = -5.0f,
        .turn_window = 0.7f,
        .turn_velocity = 0.7f,
    },
};

} // namespace BallBeamTaskProfiles

#endif
