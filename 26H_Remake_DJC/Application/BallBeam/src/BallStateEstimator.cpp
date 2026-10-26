#include "BallStateEstimator.h"

#include <algorithm>
#include <cmath>

/*
视觉估计器
*/


namespace {
constexpr uint32_t kMinimumEstimatorDtMs = 5U;
}

// 参数合规检查
bool BallStateEstimator::isConfigValid(const Config& config)
{
    return std::isfinite(config.alpha) && config.alpha >= 0 && config.alpha <= 1 &&
        std::isfinite(config.beta) && config.beta >= 0 && config.beta <= 1 &&
        std::isfinite(config.measurement_deadband_cm) && config.measurement_deadband_cm >= 0 &&
        std::isfinite(config.max_velocity_cm_s) && config.max_velocity_cm_s > 0 &&
        std::isfinite(config.max_x_step_cm) && config.max_x_step_cm > 0 &&
        config.predict_hold_ms <= 80U &&
        std::isfinite(config.predict_max_step_cm) && config.predict_max_step_cm >= 0;
}

// 保存配置
bool BallStateEstimator::configure(const Config& config)
{
    if (!isConfigValid(config)) return false;
    config_ = config;
    return true;
}

// 保存可用于估计器的最新数据
void BallStateEstimator::saveVisionMeasurement(const VisionData_t& vision_data)
{
    // 无效视觉数据不覆盖上一条有效测量，也不刷新其时间；仅在原超时窗口内继续预测。
    // 越界数据也不采用；通信层仍保留收到的原数据供诊断。
    if (!IsVisionMeasurementUsable(vision_data)) {
        return;
    }

    vision_seq = vision_data.seq;
    vision_tracking_valid = true;
    last_vision_tick_ms = vision_data.rx_tick_ms;
    ball_x_cm = vision_data.x_cm;
}

// 估计器初始化
void BallStateEstimator::initializeEstimate(const float x_cm, const uint32_t tick_ms)
{
    estimated_ball_x_cm = x_cm;
    estimated_ball_vx_cm_s = 0.0f;
    measurement_interval_start_ms = tick_ms;
    last_measurement_x_cm = x_cm;
    has_estimated_ball_state = true;
    last_estimate_tick_ms = tick_ms;
}

// 按已有速度预测位置；预测时间和位移仍受配置限制。
void BallStateEstimator::predictPosition(const uint32_t now_ms)
{
    if (!has_estimated_ball_state) {
        return;
    }

    const uint32_t elapsed_ms = now_ms - last_estimate_tick_ms;
    if (elapsed_ms < kMinimumEstimatorDtMs) {
        return;
    }

    const uint32_t predict_ms = std::min(elapsed_ms, config_.predict_hold_ms);
    const float predict_step_cm =
        std::clamp(estimated_ball_vx_cm_s * static_cast<float>(predict_ms) * 0.001f,
                   -config_.predict_max_step_cm,
                   config_.predict_max_step_cm);
    estimated_ball_x_cm += predict_step_cm;
    last_estimate_tick_ms = now_ms;
}

// 利用新测量数据对估计数据进行修正
void BallStateEstimator::correctWithMeasurement(const float measured_x_cm, const uint32_t measurement_tick_ms, const uint32_t now_ms)
{
    if (!has_estimated_ball_state) {
        initializeEstimate(measured_x_cm, now_ms);
        return;
    }

    predictPosition(now_ms);

    const float measurement_x_cm =
        (std::fabs(measured_x_cm - last_measurement_x_cm) < config_.measurement_deadband_cm)
            ? last_measurement_x_cm
            : measured_x_cm;
    const uint32_t elapsed_measurement_ms = measurement_tick_ms - measurement_interval_start_ms;
    const uint32_t measurement_dt_ms = std::max(elapsed_measurement_ms, kMinimumEstimatorDtMs);
    if (elapsed_measurement_ms >= kMinimumEstimatorDtMs) {
        measurement_interval_start_ms = measurement_tick_ms;
    }
    const float dt_s = static_cast<float>(measurement_dt_ms) * 0.001f;
    const float residual_cm = std::clamp(measurement_x_cm - estimated_ball_x_cm,
                                         -config_.max_x_step_cm,
                                         config_.max_x_step_cm);

    estimated_ball_x_cm += config_.alpha * residual_cm;
    estimated_ball_vx_cm_s += config_.beta * residual_cm / dt_s;
    estimated_ball_vx_cm_s = std::clamp(estimated_ball_vx_cm_s,
                                        -config_.max_velocity_cm_s,
                                        config_.max_velocity_cm_s);

    last_measurement_x_cm = measurement_x_cm;
    last_estimate_tick_ms = now_ms;
}

// 估计器更新数据
bool BallStateEstimator::updateEstimate(const uint32_t now_ms, BallStateEstimate_t *state)
{
    if (state == nullptr) {
        return false;
    }

    bool valid = vision_tracking_valid && (now_ms - last_vision_tick_ms <= vision_timeout_ms);
    if (valid) {
        if (!has_estimated_vision_seq || vision_seq != estimated_vision_seq) {
            estimated_vision_seq = vision_seq;
            has_estimated_vision_seq = true;
            correctWithMeasurement(ball_x_cm, last_vision_tick_ms, now_ms);
        } else if (has_estimated_ball_state) {
            predictPosition(now_ms);
        } else {
            valid = false;
        }
    }

    // 有效、无效结果都在这里填写；filtered_x_cm是现有输出字段，与估计位置相同。
    state->valid = valid ? 1U : 0U;
    state->raw_x_cm = ball_x_cm;
    state->filtered_x_cm = estimated_ball_x_cm;
    state->x_cm = estimated_ball_x_cm;
    state->vx_cm_s = estimated_ball_vx_cm_s;
    state->vision_seq = vision_seq;
    state->update_tick_ms = now_ms;
    state->vision_age_ms = (last_vision_tick_ms == 0U) ? 9999U : (now_ms - last_vision_tick_ms);

    if (!valid) {
        has_estimated_vision_seq = false;
        has_estimated_ball_state = false;
        estimated_ball_vx_cm_s = 0.0f;
    }
    return valid;
}
