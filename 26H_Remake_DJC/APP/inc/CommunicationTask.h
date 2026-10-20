#ifndef COMMUNICATION_TASK_H
#define COMMUNICATION_TASK_H

#include <stdbool.h>
#include <stdint.h>
#include "VisionFrame.h"

#ifdef __cplusplus
extern "C" {
#endif

bool Communication_GetLatestVisionFrame(VisionFrame_t *frame, uint32_t max_age_ms);
enum { COMM_MODE_NONE = 0, COMM_MODE_RUN = 1, COMM_MODE_TUNING = 2 };
enum { PI_TASK_INIT = 0, PI_REQUEST_NONE = 0 };
enum { PI_TUNING_TASK_VELOCITY = 1 };
typedef struct {
    uint32_t generation;
    uint8_t mode;
    uint8_t task_id;
    uint16_t request_seq;
    uint16_t revision;
    float kp, ki, kd, target_v_cm_s;
} PiControlRequest_t;

void Communication_ApplyMode(uint8_t mode);
void Communication_ReplyMode(uint8_t mode, uint16_t seq, uint8_t result);
bool Communication_GetControlRequest(PiControlRequest_t *request);
void Communication_ReportSuccess(uint32_t generation, bool parameters, uint16_t seq, bool success);
void StartCommunicationTask(void *argument);

#ifdef __cplusplus
}
#endif

#endif
