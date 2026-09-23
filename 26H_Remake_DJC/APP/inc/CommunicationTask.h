#ifndef COMMUNICATION_TASK_H
#define COMMUNICATION_TASK_H

#include <stdbool.h>
#include <stdint.h>
#include "VisionFrame.h"

#ifdef __cplusplus
extern "C" {
#endif

bool Communication_GetLatestVisionFrame(VisionFrame_t *frame, uint32_t max_age_ms);
void StartCommunicationTask(void *argument);

#ifdef __cplusplus
}
#endif

#endif
