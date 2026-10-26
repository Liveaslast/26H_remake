#ifndef BALL_BEAM_CONTROLLER_H
#define BALL_BEAM_CONTROLLER_H

#include <stdint.h>

#include "QDMotorController.h"
#include "BallStateEstimate.h"
#include "BallBeamTaskProfile.h"

class BallBeamController : public QDMotorController {           // 对QD电机控制器进一步封装，针对于球杆平衡控制器
public:
    struct ControlInputSnapshot {
        uint32_t tick_ms;
        float x_cm;
        float vx_cm_s;
        float target_v_cm_s;
    };

    BallBeamController(QD4310& motor,
                       const PID& pid_speed,
                       const PID& pid_angle,
                       float ctrl_ts,
                       float current_limit)
        : QDMotorController(motor, pid_speed, pid_angle, ctrl_ts, current_limit) {}

    // 只消费估计结果与控制目标；任务编号、任务阶段和估计历史不属于本类。
    // 完整替换本轮控制参数，不保留上个任务的调参值。
    void applyControlConfig(const BallBeamControlConfig& config);
    void setPositionTarget(float target_x_cm);
    void startVelocityControl(float target_v_cm_s);
    // 关闭小球闭环并下达平衡角；不伪造一次新的控制计算记录。
    void holdBalance();
    bool isControlUpdateDue(uint32_t now_ms) const;

    void disableBalance(); // 停止小球闭环，不等于电机停机。

    void startPositionTarget(float target_x_cm);
    void setBalanceAngle(float angle_rad);
    void setBallFeedforwardSplit(float pos_target_deg_per_cm, float neg_target_deg_per_cm);
    void setBallAngleLimit(float max_delta_deg);
    void setBallOuterLoopPeriod(float period_ms);
    void setBallPositionPid(float kp, float ki, float kd);
    void setBallVelocityPid(float kp, float ki, float kd);
    void setBallPositionDeadband(float deadband_cm);
    void setBallSpeedLimit(float max_target_v_cm_s);
    void setAngleCommandDeadband(float deadband_deg);

    void updateBalanceControl(const BallStateEstimate_t& state, uint32_t now_ms);

    [[nodiscard]] float getBallTarget() const { return target_x_cm; }
    [[nodiscard]] float getBalanceAngle() const { return balance_angle_rad; }
    [[nodiscard]] float getBallAngleCommand() const { return last_angle_cmd_rad; }
    [[nodiscard]] bool getLastControlInput(ControlInputSnapshot *snapshot) const;

private:
    enum class ControlMode { Disabled, Position, Velocity };
    // 本轮速度环采用的积分与限幅规则；默认值对应固定速度控制。
    struct VelocityLoopRules {
        float integral_weight{1.0f};
        float integral_leak_per_s{0.0f};
        float integral_limit_deg{2.5f};
        float feedback_limit_deg{7.0f};
        // 候选反馈超过该范围时，禁止积分继续向饱和方向增长；不是输出裁剪范围。
        float integration_lower_deg{-7.0f};
        float integration_upper_deg{7.0f};
    };
    void beginControl(ControlMode mode);
    void resetControlHistory();
    float calculatePositionVelocity(const BallStateEstimate_t& state, float error_cm, float dt_s);
    VelocityLoopRules calculatePositionVelocityRules(float error_cm, float velocity_cm_s,
                                                     float feedforward_deg) const;
    float calculateVelocityDerivative(float velocity_cm_s, float dt_s);
    float calculateVelocityCorrection(float velocity_cm_s, float target_v_cm_s, float dt_s,
                                      const VelocityLoopRules& rules);
    void outputAngle(float correction_deg, const BallStateEstimate_t& state,
                     float target_v_cm_s, uint32_t now_ms);

    static constexpr float kDegToRad = 0.017453292519943295f;

    ControlMode control_mode{ControlMode::Disabled};

    float target_x_cm{0.0f};
    float balance_angle_rad{30.665f * kDegToRad};
    BallBeamControlConfig::PositionVelocity position_velocity_gains{};
    float position_integral_cm_s{0.0f};
    float velocity_integral_deg{0.0f};
    float target_feedforward_pos_deg_per_cm{0.0f};
    float target_feedforward_neg_deg_per_cm{0.0f};
    float target_velocity_cm_s{0.0f};
    float previous_velocity_cm_s{0.0f};
    float filtered_acceleration_cm_s2{0.0f};
    bool has_previous_velocity{false};
    float max_angle_delta_deg{3.0f};
    float x_deadband_cm{0.27f};
    uint32_t ball_outer_loop_period_ms{10U};
    ControlInputSnapshot last_control_input{};
    bool has_last_control_input{false};
    float angle_cmd_deadband_deg{0.03f};

    float angle_reference_rad{30.665f * kDegToRad};
    float last_angle_cmd_rad{30.665f * kDegToRad};
    float last_sent_angle_cmd_rad{30.665f * kDegToRad};
    uint32_t last_control_tick_ms{0U};
};

#endif
