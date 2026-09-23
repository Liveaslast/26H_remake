#ifndef BALL_STATE_ESTIMATE_H
#define BALL_STATE_ESTIMATE_H

#include <stdint.h>
#include "cmsis_os.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float raw_x_cm;
    float raw_vx_cm_s;
    float filtered_x_cm;
    float x_cm;
    float vx_cm_s;
    uint8_t valid;
    uint16_t vision_seq;
    uint32_t update_tick_ms;
    uint32_t vision_age_ms;
} BallStateEstimate_t;

extern osMessageQueueId_t BallStateQueueHandle;

void BallStateStoreLatest(const BallStateEstimate_t *state);
uint8_t BallStateGetLatest(BallStateEstimate_t *state);

#ifdef __cplusplus
}
#endif

#endif
