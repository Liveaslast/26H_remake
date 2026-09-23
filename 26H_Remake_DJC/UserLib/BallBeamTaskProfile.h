#ifndef BALL_BEAM_TASK_PROFILE_H
#define BALL_BEAM_TASK_PROFILE_H

#include <stdint.h>

struct BallBeamTaskProfile {
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
    .feedforward = {.positive = 0.9f, .negative = 0.45f},
    .brake = {
        .short_kp = 0.35f,
        .short_margin = 2.0f,
        .short_max = 2.5f,
        .short_dist = 5.0f,
        .long_kp = 0.45f,
        .long_margin = 5.5f,
        .long_max = 4.0f,
        .long_dist = 10.0f,
        .speed_kp = 0.35f,
        .speed_target = 1.0f,
        .speed_max = 4.0f,
        .negative_max = 5.5f,
    },
    .terminal = {
        .brake_window = 0.6f,
        .brake_velocity = 1.0f,
        .push_positive_window = 1.8f,
        .push_positive_velocity = 1.2f,
        .push_positive_kp = 2.0f,
        .push_negative_window = 1.8f,
        .push_negative_velocity = 1.2f,
        .push_negative_kp = 2.0f,
    },
    .sequence = {
        .first_target = 5.0f,
        .second_target = -5.0f,
        .turn_window = 0.7f,
        .turn_velocity = 0.7f,
    },
    .balance_angle_deg = 22.0f,
    .angle_rate_deg_per_s = 0.0f,
    .angle_command_limit_deg = 8.0f,
    .x_deadband_cm = 0.25f,
    .vx_deadband_cm_s = 0.5f,
    .outer_loop_period_ms = 20.0f,
};

} // namespace BallBeamTaskProfiles

#endif
