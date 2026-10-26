#ifndef BALL_STATE_ESTIMATOR_H
#define BALL_STATE_ESTIMATOR_H

#include "BallStateEstimate.h"
#include "VisionData.h"

// a-b滤波估计器
class BallStateEstimator {
public:
    struct Config {                                     // a-b滤波配置参数
        float alpha = 0.35f;
        float beta = 0.025f;
        float measurement_deadband_cm = 0.04f;
        float max_velocity_cm_s = 45.0f;
        float max_x_step_cm = 3.0f;
        uint32_t predict_hold_ms = 35U;
        float predict_max_step_cm = 0.35f;
    };

    static bool isConfigValid(const Config& config);
    bool configure(const Config& config);
    // 保存可用测量；不执行a-b计算，无效测量不覆盖上一条有效测量。
    void saveVisionMeasurement(const VisionData_t& vision_data);
    // 每轮填写state，包括无效状态；true表示本轮估计有效。单位cm、cm/s、MCU毫秒。
    bool updateEstimate(uint32_t now_ms, BallStateEstimate_t *state);

private:
    void initializeEstimate(float x_cm, uint32_t tick_ms);
    void predictPosition(uint32_t now_ms);
    void correctWithMeasurement(float measured_x_cm, uint32_t measurement_tick_ms, uint32_t now_ms);

    Config config_{};
    bool vision_tracking_valid{false};
    uint16_t vision_seq{0U};
    uint32_t last_vision_tick_ms{0U};
    static constexpr uint32_t vision_timeout_ms = 100U;
    float ball_x_cm{0.0f};
    // a-b速度修正的测量间隔起点；间隔不足5ms时保留起点，继续累计。
    uint32_t measurement_interval_start_ms{0U};
    float estimated_ball_x_cm{0.0f};
    float estimated_ball_vx_cm_s{0.0f};
    float last_measurement_x_cm{0.0f};
    bool has_estimated_ball_state{false};
    uint16_t estimated_vision_seq{0U};
    bool has_estimated_vision_seq{false};
    uint32_t last_estimate_tick_ms{0U};
};

#endif
