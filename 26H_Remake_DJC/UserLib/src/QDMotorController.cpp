#include "QDMotorController.h"

#include <algorithm>

float QDMotorController::wrap(float value, const float min, const float max)
{
    value = std::fmod(value - min, max - min);
    return value < 0.0f ? value + max : value + min;
}

namespace {

constexpr float kTwoPi = 2.0f * std::numbers::pi_v<float>;

float unwrap_near(float value, const float reference)
{
    while ((value - reference) > kTwoPi) {
        value -= kTwoPi;
    }
    while ((value - reference) < -kTwoPi) {
        value += kTwoPi;
    }
    if ((value - reference) > std::numbers::pi_v<float>) {
        value -= kTwoPi;
    } else if ((value - reference) < -std::numbers::pi_v<float>) {
        value += kTwoPi;
    }
    return value;
}

} // namespace

float QDMotorController::clamp_current(const float current) const
{
    return std::clamp(current, -current_limit, current_limit);
}

float QDMotorController::clamp_angle_target(const float angle) const
{
    if (!angle_limit_enabled) {
        return angle;
    }
    return std::clamp(angle, angle_min, angle_max);
}

float QDMotorController::update_ramped_angle_target()
{
    const float max_step = std::max(0.0f, angle_rate_limit) * Ts;
    const float error = target_angle - ramped_target_angle;

    if ((max_step <= 0.0f) || (std::fabs(error) <= max_step)) {
        ramped_target_angle = target_angle;
    } else {
        ramped_target_angle += (error > 0.0f) ? max_step : -max_step;
    }

    ramped_target_angle = clamp_angle_target(ramped_target_angle);
    return ramped_target_angle;
}

void QDMotorController::apply_pid_output_limit()
{
    pid_speed.output_limit_p = current_limit;
    pid_speed.output_limit_n = -current_limit;
    pid_angle.output_limit_p = current_limit;
    pid_angle.output_limit_n = -current_limit;
}

void QDMotorController::update_feedback()
{
    raw_motor_angle = motor.angle;
    if (zero_point_set) {
        motor_angle = unwrap_near(raw_motor_angle - zero_point_angle, previous_angle);
    } else {
        motor_angle = unwrap_near(raw_motor_angle, previous_angle);
    }
    motor_speed = motor.speed;
    motor_current = motor.current;
}

void QDMotorController::init()
{
    apply_pid_output_limit();
    update_feedback();
    target_angle = motor_angle;
    ramped_target_angle = motor_angle;
    previous_angle = motor_angle;
    initialized = true;
}

void QDMotorController::enable()
{
    if (!initialized || enabled) {
        return;
    }

    motor.enable();
    enabled = true;
}

void QDMotorController::disable()
{
    if (!enabled) {
        return;
    }

    motor.setCurrent(0.0f);
    motor.disable();
    target_current = 0.0f;
    started = false;
    enabled = false;
}

void QDMotorController::start()
{
    if (enabled) {
        started = true;
    }
}

void QDMotorController::stop()
{
    started = false;
    Ctrl(CtrlType::CurrentCtrl, 0.0f);
    motor.setCurrent(0.0f);
}

void QDMotorController::Ctrl(const CtrlType ctrl_type, const float value)
{
    update_feedback();

    switch (ctrl_type) {
    case CtrlType::LowSpeedCtrl:
        target_low_speed = value;
        if (this->ctrl_type != ctrl_type) {
            target_angle = clamp_angle_target(motor_angle);
            ramped_target_angle = target_angle;
        }
        break;
    case CtrlType::StepAngleCtrl:
        if (this->ctrl_type == ctrl_type) {
            target_angle = clamp_angle_target(target_angle + value);
        } else {
            target_angle = clamp_angle_target(motor_angle + value);
            ramped_target_angle = motor_angle;
        }
        break;
    case CtrlType::AngleCtrl:
        if ((this->ctrl_type != CtrlType::AngleCtrl) &&
            (this->ctrl_type != CtrlType::StepAngleCtrl) &&
            (this->ctrl_type != CtrlType::LowSpeedCtrl)) {
            ramped_target_angle = motor_angle;
        }
        target_angle = clamp_angle_target(motor_angle + wrap(value - motor_angle));
        break;
    case CtrlType::SpeedCtrl:
        target_speed = value;
        break;
    case CtrlType::CurrentCtrl:
        target_current = clamp_current(value);
        break;
    }

    this->ctrl_type = ctrl_type;
}

void QDMotorController::Ctrl_ISR()
{
    update_feedback();

    if (!enabled) {
        return;
    }

    if (!started) {
        motor.setCurrent(0.0f);
        return;
    }

    switch (ctrl_type) {
    case CtrlType::LowSpeedCtrl:
        target_angle = clamp_angle_target(target_angle + target_low_speed * Ts * two_pi / 60.0f);
        ramped_target_angle = target_angle;
        [[fallthrough]];
    case CtrlType::AngleCtrl:
    case CtrlType::StepAngleCtrl:
        if ((previous_angle - motor_angle) > std::numbers::pi_v<float>) {
            target_angle -= two_pi;
            ramped_target_angle -= two_pi;
        } else if ((previous_angle - motor_angle) < -std::numbers::pi_v<float>) {
            target_angle += two_pi;
            ramped_target_angle += two_pi;
        }

        target_angle = clamp_angle_target(target_angle);
        pid_angle.target = update_ramped_angle_target();
        target_current = clamp_current(pid_angle.calc(motor_angle));
        motor.setCurrent(target_current);
        break;
    case CtrlType::SpeedCtrl:
        pid_speed.target = target_speed;
        target_current = clamp_current(pid_speed.calc(motor_speed));
        motor.setCurrent(target_current);
        break;
    case CtrlType::CurrentCtrl:
        target_current = clamp_current(target_current);
        motor.setCurrent(target_current);
        break;
    }

    previous_angle = motor_angle;
}

void QDMotorController::setSpeedPID(const float kp, const float ki, const float kd)
{
    pid_speed.kp = kp;
    pid_speed.ki = ki;
    pid_speed.kd = kd;
}

void QDMotorController::setAnglePID(const float kp, const float ki, const float kd)
{
    pid_angle.kp = kp;
    pid_angle.ki = ki;
    pid_angle.kd = kd;
}

void QDMotorController::setCurrentLimit(const float limit)
{
    current_limit = std::max(0.0f, limit);
    target_current = clamp_current(target_current);
    apply_pid_output_limit();
}

void QDMotorController::setAngleLimit(float min_angle, float max_angle)
{
    if (min_angle > max_angle) {
        std::swap(min_angle, max_angle);
    }
    angle_min = min_angle;
    angle_max = max_angle;
    angle_limit_enabled = true;
    target_angle = clamp_angle_target(target_angle);
    ramped_target_angle = clamp_angle_target(ramped_target_angle);
}

void QDMotorController::disableAngleLimit()
{
    angle_limit_enabled = false;
}

void QDMotorController::setAngleRateLimit(const float rate_limit)
{
    angle_rate_limit = std::max(0.0f, rate_limit);
}

void QDMotorController::setZeroPoint()
{
    raw_motor_angle = motor.angle;
    zero_point_angle = raw_motor_angle;
    zero_point_set = true;
    motor_angle = 0.0f;
    motor_speed = motor.speed;
    motor_current = motor.current;

    target_angle = motor_angle;
    ramped_target_angle = motor_angle;
    previous_angle = motor_angle;
    pid_angle.clear();
    pid_speed.clear();
}

void QDMotorController::clearZeroPoint()
{
    zero_point_angle = 0.0f;
    zero_point_set = false;
    update_feedback();

    target_angle = motor_angle;
    ramped_target_angle = motor_angle;
    previous_angle = motor_angle;
    pid_angle.clear();
    pid_speed.clear();
}
