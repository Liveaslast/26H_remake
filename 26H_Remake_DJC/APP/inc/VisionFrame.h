#ifndef VISION_FRAME_H
#define VISION_FRAME_H

#include <stdint.h>
#include "cmsis_os.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int32_t ball_pos_001cm;
    int32_t ball_vel_001cms;
    uint8_t tracking_valid;
    uint16_t seq;
    uint32_t pi_time_ms;
    uint32_t rx_tick_ms;
} VisionFrame_t;

extern osMessageQueueId_t VisionFrameQueueHandle;

#ifdef __cplusplus
}
#endif

#endif
