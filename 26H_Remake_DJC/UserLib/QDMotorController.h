#ifndef QD_MOTOR_CONTROLLER_H
#define QD_MOTOR_CONTROLLER_H

#include <cmath>
#include <numbers>

#include "PID.h"
#include "QD4310.h"

class QDMotorController {
public:
    enum class CtrlType {
        CurrentCtrl = 0,
        SpeedCtrl = 1,
        AngleCtrl = 2,
        StepAngleCtrl = 3,
        LowSpeedCtrl = 4,
    };

    QDMotorController(QD4310& motor,
                      const PID& pid_speed,
                      const PID& pid_angle,
                      float ctrl_ts,
                      float current_limit)
        : Ts(ctrl_ts), pid_speed(pid_speed), pid_angle(pid_angle), motor(motor), current_limit(current_limit) {}

    bool initialized{false};
    bool enabled{false};
    bool started{false};

    float motor_angle{0.0f};
    float raw_motor_angle{0.0f};
    float motor_speed{0.0f};
    float motor_current{0.0f};

    [[nodiscard]] CtrlType getCtrlType() const { return ctrl_type; }
    [[nodiscard]] float getTargetCurrent() const { return target_current; }
    [[nodiscard]] float getTargetSpeed() const { return target_speed; }
    [[nodiscard]] float getTargetAngle() const { return target_angle; }
    [[nodiscard]] float getRampedTargetAngle() const { return ramped_target_angle; }
    [[nodiscard]] float getTargetLowSpeed() const { return target_low_speed; }
    [[nodiscard]] float getAngleRateLimit() const { return angle_rate_limit; }
    [[nodiscard]] float getCurrentLimit() const { return current_limit; }
    [[nodiscard]] bool isAngleLimitEnabled() const { return angle_limit_enabled; }
    [[nodiscard]] float getAngleMin() const { return angle_min; }
    [[nodiscard]] float getAngleMax() const { return angle_max; }
    [[nodiscard]] float getSpeedPidKp() const { return pid_speed.kp; }
    [[nodiscard]] float getSpeedPidKi() const { return pid_speed.ki; }
    [[nodiscard]] float getSpeedPidKd() const { return pid_speed.kd; }
    [[nodiscard]] float getAnglePidKp() const { return pid_angle.kp; }
    [[nodiscard]] float getAnglePidKi() const { return pid_angle.ki; }
    [[nodiscard]] float getAnglePidKd() const { return pid_angle.kd; }
    [[nodiscard]] float getZeroPointAngle() const { return zero_point_angle; }
    [[nodiscard]] bool isZeroPointSet() const { return zero_point_set; }

    void init();
    void enable();
    void disable();
    void start();
    void stop();

    void Ctrl(CtrlType ctrl_type, float value);
    void Ctrl_ISR();
    void update_feedback();

    void setSpeedPID(float kp, float ki, float kd);
    void setAnglePID(float kp, float ki, float kd);
    void setCurrentLimit(float limit);
    void setAngleLimit(float min_angle, float max_angle);
    void disableAngleLimit();
    void setAngleRateLimit(float rate_limit);
    void setZeroPoint();
    void clearZeroPoint();

private:
    static constexpr float two_pi = 2.0f * std::numbers::pi_v<float>;

    float Ts;
    PID pid_speed;
    PID pid_angle;
    QD4310& motor;

    CtrlType ctrl_type{CtrlType::CurrentCtrl};
    float target_low_speed{0.0f};
    float target_angle{0.0f};
    float ramped_target_angle{0.0f};
    float target_speed{0.0f};
    float target_current{0.0f};
    // Default to no software angle-rate limit; runtime `arate` can still enable one.
    float angle_rate_limit{0.0f};
    float current_limit{0.30f};
    bool angle_limit_enabled{false};
    float angle_min{0.0f};
    float angle_max{0.0f};
    float zero_point_angle{0.0f};
    bool zero_point_set{false};
    float previous_angle{0.0f};

    static float wrap(float value,
                      float min = -std::numbers::pi_v<float>,
                      float max = std::numbers::pi_v<float>);
    float clamp_current(float current) const;
    float clamp_angle_target(float angle) const;
    float update_ramped_angle_target();
    void apply_pid_output_limit();
};

#endif
