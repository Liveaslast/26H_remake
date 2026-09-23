#ifndef BALL_BEAM_CONTROLLER_H
#define BALL_BEAM_CONTROLLER_H

#include <stdint.h>

#include "QDMotorController.h"
#include "VisionFrame.h"
#include "BallStateEstimate.h"
#include "BallBeamTaskProfile.h"

class BallBeamController : public QDMotorController {
public:
    enum class TaskId : uint8_t {
        None = 0U,
        Task1 = 1U,
    };

    BallBeamController(QD4310& motor,
                       const PID& pid_speed,
                       const PID& pid_angle,
                       float ctrl_ts,
                       float current_limit)
        : QDMotorController(motor, pid_speed, pid_angle, ctrl_ts, current_limit) {}

    void enableBalance();
    void disableBalance();
    [[nodiscard]] bool isBalanceEnabled() const { return balance_enabled; }

    void setBallTarget(float target_x_cm);
    void startBallSequence(float first_target_x_cm, float second_target_x_cm, float turn_window_cm, float turn_vx_cm_s);
    void setBalanceAngle(float angle_rad);
    void setBalanceTable(float neg5_deg, float zero_deg, float pos5_deg);
    void setBallGains(float kp_deg_per_cm, float ki_deg_per_cm_s, float kd_deg_per_cm_s);
    void setBallFeedforward(float target_deg_per_cm);
    void setBallFeedforwardSplit(float pos_target_deg_per_cm, float neg_target_deg_per_cm);
    void setBallVisionWeight(float far_error_cm, float near_error_cm, float min_weight);
    void setBallDWeight(float far_error_cm, float near_error_cm, float min_weight);
    void setBallBrakeP(float kp_deg_per_cm, float margin_cm, float max_angle_deg);
    void setBallBrakePShortProfile(float kp_deg_per_cm, float margin_cm, float max_angle_deg, float move_dist_cm);
    void setBallBrakePLongProfile(float kp_deg_per_cm, float margin_cm, float max_angle_deg, float move_dist_cm);
    void setBallBrakePSpeed(float kp_deg_per_cm_s, float target_vx_cm_s, float max_angle_deg);
    void setBallBrakePNegativeMax(float max_angle_deg);
    void setBallTerminalBrakeGate(float x_window_cm, float vx_window_cm_s);
    void setBallTerminalPush(float window_cm, float vx_window_cm_s, float kp_deg_per_cm, float max_angle_deg);
    void setBallTerminalPushPositive(float window_cm, float vx_window_cm_s, float kp_deg_per_cm, float max_angle_deg);
    void setBallTerminalPushNegative(float window_cm, float vx_window_cm_s, float kp_deg_per_cm, float max_angle_deg);
    void setBallAngleLimit(float max_delta_deg);
    void setBallDeadband(float x_deadband_cm, float vx_deadband_cm_s);
    void setBallOuterLoopPeriod(float period_ms);
    void setVisionFilter(float x_alpha, float vx_alpha, float dx_deadband_cm);
    void setVisionMeasurementDeadband(float deadband_cm);
    void setVisionFilterLimits(float max_velocity_cm_s, float interp_duration_ms, float max_x_step_cm);
    void setVisionVelocity(float window_points, float min_dx_cm, float reverse_limit);
    void setVisionPrediction(float sample_interval_ms, float predict_ms, float predict_step_cm);
    void setVisionAbCorrectionLimit(float max_correction_step_cm);
    void setAngleCommandDeadband(float deadband_deg);
    void setVisionTimeout(uint32_t timeout_ms);

    bool startTask(TaskId task);
    void initializeTask();
    void stopTask();
    [[nodiscard]] TaskId getActiveTask() const { return active_task; }
    [[nodiscard]] bool isTaskActive() const { return active_task != TaskId::None; }

    void updateVisionRaw(const VisionFrame_t& frame);
    bool updateBallStateEstimator(uint32_t now_ms, BallStateEstimate_t *state);
    void updateBalanceControl(const BallStateEstimate_t& state, uint32_t now_ms);
    void updateVision(const VisionFrame_t& frame);
    void Balance_ISR(uint32_t now_ms);

    [[nodiscard]] float getBallTarget() const { return target_x_cm; }
    [[nodiscard]] float getBalanceAngle() const { return balance_angle_rad; }
    [[nodiscard]] float getBalanceAngleForTarget(float target_x_cm) const;
    [[nodiscard]] float getBallKp() const { return kp_deg_per_cm; }
    [[nodiscard]] float getBallKi() const { return ki_deg_per_cm_s; }
    [[nodiscard]] float getBallKd() const { return kd_deg_per_cm_s; }
    [[nodiscard]] float getBallFeedforward() const { return target_feedforward_deg_per_cm; }
    [[nodiscard]] float getBallAngleLimit() const { return max_angle_delta_deg; }
    [[nodiscard]] float getBallXDeadband() const { return x_deadband_cm; }
    [[nodiscard]] float getBallVxDeadband() const { return vx_deadband_cm_s; }
    [[nodiscard]] float getAngleCommandDeadband() const { return angle_cmd_deadband_deg; }
    [[nodiscard]] float getBallX() const { return ball_x_cm; }
    [[nodiscard]] float getBallVx() const { return raw_vision_diff_vx_cm_s; }
    [[nodiscard]] float getEstimatedBallX() const { return output_ball_x_cm; }
    [[nodiscard]] float getEstimatedBallVx() const { return output_ball_vx_cm_s; }
    [[nodiscard]] float getBallControlDx() const { return last_control_dx_cm; }
    [[nodiscard]] float getBallRawControlDx() const { return last_raw_control_dx_cm; }
    [[nodiscard]] float getBallError() const { return last_error_cm; }
    [[nodiscard]] float getBallAngleCommand() const { return last_angle_cmd_rad; }
    [[nodiscard]] float getBallBrakePOffsetDeg() const { return last_brake_p_offset_deg; }
    [[nodiscard]] float getBallTerminalOffsetDeg() const { return last_terminal_trim_deg; }
    [[nodiscard]] bool isBallBrakePActive() const { return last_brake_p_active; }
    [[nodiscard]] bool isBallTerminalPushActive() const { return last_terminal_push_active; }
    [[nodiscard]] bool isBallTerminalTrimActive() const { return last_terminal_trim_active; }
    [[nodiscard]] bool isBallTerminalBrakeGateActive() const { return last_terminal_brake_gate_active; }
    [[nodiscard]] bool isBallStalledBeforeTerminal() const { return last_stalled_before_terminal; }
    [[nodiscard]] uint8_t getBallSequenceStage() const { return ball_sequence_stage; }
    [[nodiscard]] bool isVisionFresh(uint32_t now_ms) const;
    [[nodiscard]] bool isVisionTrackingValid() const { return vision_tracking_valid; }
    [[nodiscard]] uint16_t getVisionSeq() const { return vision_seq; }
    [[nodiscard]] uint32_t getLastVisionTick() const { return last_vision_tick_ms; }
    [[nodiscard]] uint32_t getVisionTimeout() const { return vision_timeout_ms; }

private:
    static constexpr float kDegToRad = 0.017453292519943295f;
    static constexpr uint8_t kVisionVelocityHistoryCapacity = 5U;

    typedef struct {
        float x_cm;
        uint32_t tick_ms;
    } VisionVelocityPoint_t;

    void resetBallStateEstimator(float x_cm, uint32_t tick_ms);
    void predictBallStateTo(uint32_t now_ms);
    void updateBallStateWithMeasurement(float measured_x_cm, uint32_t measurement_tick_ms, uint32_t now_ms);
    void updateRawVisionDiffVelocity(float measured_x_cm, uint32_t tick_ms);
    float calculateInterpolatedX(uint32_t now_ms, bool include_prediction) const;
    void fillPredictedBallState(uint32_t now_ms, BallStateEstimate_t *state) const;
    void resetVisionVelocityHistory(float x_cm, uint32_t tick_ms);
    void pushVisionVelocityPoint(float x_cm, uint32_t tick_ms);
    bool estimateVisionVelocity(float *vx_cm_s) const;
    float calculateVisionWeight(float abs_error_cm) const;
    float calculateWeight(float abs_error_cm, float far_error_cm, float near_error_cm, float min_weight) const;
    float calculateDWeight(float abs_error_cm) const;
    void updateVisionVelocityFromCleanPosition(float clean_x_cm, uint32_t tick_ms);
    void updateEffectiveBrakePForMove();
    void applyBallTarget(float target_x_cm);
    void applyTaskProfile(const BallBeamTaskProfile& profile);
    void startTask1SequenceWhenReady();

    bool balance_enabled{false};
    TaskId active_task{TaskId::None};
    bool vision_tracking_valid{false};
    uint16_t vision_seq{0U};
    uint16_t last_control_vision_seq{0U};
    bool has_control_vision_seq{false};
    uint32_t last_vision_tick_ms{0U};
    uint32_t vision_timeout_ms{100U};

    float target_x_cm{0.0f};
    float balance_angle_neg5_deg{27.45f};
    float balance_angle_zero_deg{30.665f};
    float balance_angle_pos5_deg{34.45f};
    float balance_angle_rad{30.665f * kDegToRad};
    float kp_deg_per_cm{0.35f};
    float ki_deg_per_cm_s{0.0f};
    float kd_deg_per_cm_s{0.0f};
    float target_feedforward_deg_per_cm{0.0f};
    float target_feedforward_pos_deg_per_cm{0.0f};
    float target_feedforward_neg_deg_per_cm{0.0f};
    float vision_weight_far_error_cm{3.0f};
    float vision_weight_near_error_cm{1.0f};
    float vision_weight_min{0.10f};
    float d_weight_far_error_cm{2.2f};
    float d_weight_near_error_cm{0.8f};
    float d_weight_min{0.0f};
    float brake_p_kp_deg_per_cm{0.0f};
    float brake_p_margin_cm{1.2f};
    float brake_p_max_angle_deg{3.0f};
    float brake_p_short_kp_deg_per_cm{0.0f};
    float brake_p_short_margin_cm{1.2f};
    float brake_p_short_max_angle_deg{3.0f};
    float brake_p_short_dist_cm{5.0f};
    float brake_p_long_kp_deg_per_cm{0.0f};
    float brake_p_long_margin_cm{1.2f};
    float brake_p_long_max_angle_deg{3.0f};
    float brake_p_long_dist_cm{10.0f};
    float brake_p_speed_kp_deg_per_cm_s{0.25f};
    float brake_p_speed_target_vx_cm_s{1.0f};
    float brake_p_speed_max_angle_deg{3.2f};
    float brake_p_negative_max_angle_override_deg{-1.0f};
    float target_start_x_cm{0.0f};
    float target_move_dist_cm{0.0f};
    bool ball_sequence_active{false};
    // A repeated `task 1` may arrive while the ball is still at the previous
    // task endpoint.  Bring it back to the fixed zero first, without changing
    // the stored zero point, then launch the normal +5 -> -5 sequence.
    bool task_start_pending{false};
    uint8_t ball_sequence_stage{0U};
    float ball_sequence_first_target_cm{5.0f};
    float ball_sequence_second_target_cm{-5.0f};
    float ball_sequence_turn_window_cm{0.5f};
    float ball_sequence_turn_vx_cm_s{0.6f};
    float terminal_brake_x_window_cm{0.60f};
    float terminal_brake_vx_window_cm_s{20.0f};
    float terminal_push_window_cm{0.0f};
    float terminal_push_vx_window_cm_s{5.0f};
    float terminal_push_kp_deg_per_cm{0.0f};
    float terminal_push_max_angle_deg{0.0f};
    float terminal_push_pos_window_cm{0.0f};
    float terminal_push_pos_vx_window_cm_s{5.0f};
    float terminal_push_pos_kp_deg_per_cm{0.0f};
    float terminal_push_pos_max_angle_deg{0.0f};
    float terminal_push_neg_window_cm{0.0f};
    float terminal_push_neg_vx_window_cm_s{5.0f};
    float terminal_push_neg_kp_deg_per_cm{0.0f};
    float terminal_push_neg_max_angle_deg{0.0f};
    // Historical name retained only for CSV/API compatibility.  The value is
    // now the active terminal BPUSH offset; there is no BTRIM controller.
    float terminal_trim_deadband_cm{0.15f};
    float last_terminal_trim_deg{0.0f};
    bool terminal_correction_latched{false};
    bool brake_p_active{false};
    float brake_p_active_direction{0.0f};
    float target_motion_direction{0.0f};
    float last_brake_p_offset_deg{0.0f};
    bool last_brake_p_active{false};
    bool last_terminal_push_active{false};
    bool last_terminal_trim_active{false};
    bool last_terminal_brake_gate_active{false};
    bool last_stalled_before_terminal{false};
    float max_angle_delta_deg{3.0f};
    float x_deadband_cm{0.27f};
    float vx_deadband_cm_s{2.5f};
    uint32_t ball_outer_loop_period_ms{10U};
    float vision_x_alpha{0.35f};
    float vision_vx_alpha{0.025f};
    float vision_measurement_deadband_cm{0.04f};
    float vision_dx_deadband_cm{0.04f};
    float vision_static_velocity_decay{0.70f};
    float vision_max_velocity_cm_s{45.0f};
    float vision_interp_duration_ms{55.0f};
    float vision_max_x_step_cm{3.0f};
    float vision_ab_max_correction_step_cm{0.18f};
    uint32_t vision_velocity_sample_interval_ms{25U};
    uint32_t vision_predict_hold_ms{35U};
    float vision_predict_max_step_cm{0.35f};
    uint8_t vision_velocity_window_points{3U};
    float vision_velocity_min_dx_cm{0.10f};
    uint8_t vision_velocity_reverse_limit{1U};
    float angle_cmd_deadband_deg{0.03f};
    float integral_limit_cm_s{8.0f};

    float ball_x_cm{0.0f};
    float ball_vx_cm_s{0.0f};
    float raw_vision_diff_vx_cm_s{0.0f};
    float last_raw_vision_x_cm{0.0f};
    uint32_t last_raw_vision_tick_ms{0U};
    bool has_last_raw_vision_sample{false};
    float estimated_ball_x_cm{0.0f};
    float filtered_ball_x_cm{0.0f};
    float estimated_ball_vx_cm_s{0.0f};
    float last_measurement_x_cm{0.0f};
    float interpolation_start_x_cm{0.0f};
    float interpolation_target_x_cm{0.0f};
    uint32_t interpolation_start_tick_ms{0U};
    uint32_t interpolation_duration_ms{40U};
    VisionVelocityPoint_t vision_velocity_history[kVisionVelocityHistoryCapacity] = {};
    uint8_t vision_velocity_history_head{0U};
    uint8_t vision_velocity_history_count{0U};
    uint32_t last_velocity_sample_tick_ms{0U};
    float output_ball_x_cm{0.0f};
    float output_ball_vx_cm_s{0.0f};
    bool has_estimated_ball_state{false};
    uint16_t estimated_vision_seq{0U};
    bool has_estimated_vision_seq{false};
    uint32_t last_estimate_tick_ms{0U};
    float ball_error_integral_cm_s{0.0f};
    float last_error_cm{0.0f};
    float previous_error_cm{0.0f};
    float previous_previous_error_cm{0.0f};
    bool has_incremental_pid_history{false};
    float last_raw_control_dx_cm{0.0f};
    float last_control_dx_cm{0.0f};
    float last_control_x_cm{0.0f};
    bool has_last_control_x{false};
    float angle_reference_rad{30.665f * kDegToRad};
    float last_angle_cmd_rad{30.665f * kDegToRad};
    float last_sent_angle_cmd_rad{30.665f * kDegToRad};
    uint32_t last_control_tick_ms{0U};
};

#endif








