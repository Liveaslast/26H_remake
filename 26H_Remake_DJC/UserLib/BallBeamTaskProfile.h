#ifndef BALL_BEAM_TASK_PROFILE_H
#define BALL_BEAM_TASK_PROFILE_H

#include <stdint.h>

struct BallBeamTaskProfile {
    enum class ControlMode : uint8_t {
        LegacyBrakePush,
        PositionVelocity,
    };

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

    ControlMode control_mode;
    struct Feedforward {
        float positive;
        float negative;
    } feedforward;

    struct Brake {
        float short_kp;
        float short_margin;
        float short_max;
        float short_dist;
        float long_kp;
        float long_margin;
        float long_max;
        float long_dist;
        float speed_kp;
        float speed_target;
        float speed_max;
        float negative_max;
    } brake;

    struct Terminal {
        float brake_window;
        float brake_velocity;
        float push_positive_window;
        float push_positive_velocity;
        float push_positive_kp;
        float push_negative_window;
        float push_negative_velocity;
        float push_negative_kp;
    } terminal;

    struct Sequence {
        float first_target;
        float second_target;
        float turn_window;
        float turn_velocity;
    } sequence;

    float balance_angle_deg;
    float angle_rate_deg_per_s;
    float angle_command_limit_deg;
    float x_deadband_cm;
    float vx_deadband_cm_s;
    float outer_loop_period_ms;
};

namespace BallBeamTaskProfiles {

inline constexpr BallBeamTaskProfile Task1{
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
    .control_mode = BallBeamTaskProfile::ControlMode::PositionVelocity,
    .feedforward = {.positive = 0.9f, .negative = 0.45f},
    .brake = {
        .short_kp = 0.35f,
        .short_margin = 3.0f,
        .short_max = 4.0f,
        .short_dist = 5.0f,
        .long_kp = 0.45f,
        .long_margin = 4.5f,
        .long_max = 4.0f,
        .long_dist = 10.0f,
        .speed_kp = 0.35f,
        .speed_target = 1.0f,
        .speed_max = 4.0f,
        .negative_max = 4.0f,
    },
    .terminal = {
        .brake_window = 0.6f,
        .brake_velocity = 1.0f,
        .push_positive_window = 0.0f,
        .push_positive_velocity = 0.0f,
        .push_positive_kp = 0.0f,
        .push_negative_window = 1.0f,
        .push_negative_velocity = 2.0f,
        .push_negative_kp = 2.0f,
    },
    .sequence = {
        .first_target = 5.0f,
        .second_target = -5.0f,
        .turn_window = 0.7f,
        .turn_velocity = 0.7f,
    },
    .balance_angle_deg = 21.0f,
    .angle_rate_deg_per_s = 0.0f,
    .angle_command_limit_deg = 8.0f,
    .x_deadband_cm = 0.25f,
    .vx_deadband_cm_s = 0.5f,
    .outer_loop_period_ms = 20.0f,
};

} // namespace BallBeamTaskProfiles

#endif
