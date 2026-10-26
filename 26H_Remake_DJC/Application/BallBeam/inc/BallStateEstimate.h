#ifndef BALL_STATE_ESTIMATE_H
#define BALL_STATE_ESTIMATE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// 小球状态估计容器
typedef struct {
    float raw_x_cm;
    float filtered_x_cm;
    float x_cm;
    float vx_cm_s;
    uint8_t valid;
    uint16_t vision_seq;
    uint32_t update_tick_ms;
    uint32_t vision_age_ms;
} BallStateEstimate_t;

#ifdef __cplusplus
}
#endif

#endif
