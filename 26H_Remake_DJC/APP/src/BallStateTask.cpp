#include "BallStateTask.h"

#include "BallStateEstimate.h"
#include "BallBeamController.h"
#include "CommunicationTask.h"
#include "VisionFrame.h"

#include "FreeRTOS.h"
#include "cmsis_os.h"
#include "task.h"

extern BallBeamController qd_controller;

namespace {

constexpr uint32_t kBallStatePeriodMs = 2U;
BallStateEstimate_t latest_ball_state = {};
bool latest_ball_state_valid = false;

void PublishLatestState(const BallStateEstimate_t& state)
{
    BallStateStoreLatest(&state);

    if (BallStateQueueHandle == nullptr) {
        return;
    }

    if (osMessageQueuePut(BallStateQueueHandle, &state, 0U, 0U) == osOK) {
        return;
    }

    BallStateEstimate_t dropped = {};
    while (osMessageQueueGet(BallStateQueueHandle, &dropped, nullptr, 0U) == osOK) {
    }
    (void)osMessageQueuePut(BallStateQueueHandle, &state, 0U, 0U);
}

} // namespace

extern "C" void BallStateStoreLatest(const BallStateEstimate_t *state)
{
    if (state == nullptr) {
        return;
    }

    taskENTER_CRITICAL();
    latest_ball_state = *state;
    latest_ball_state_valid = true;
    taskEXIT_CRITICAL();
}

extern "C" uint8_t BallStateGetLatest(BallStateEstimate_t *state)
{
    if (state == nullptr) {
        return 0U;
    }

    bool valid = false;
    taskENTER_CRITICAL();
    valid = latest_ball_state_valid;
    if (valid) {
        *state = latest_ball_state;
    }
    taskEXIT_CRITICAL();
    return valid ? 1U : 0U;
}

extern "C" void BallStateTask(void *argument)
{
    (void)argument;

    while (BallStateQueueHandle == nullptr) {
        osDelay(1);
    }

    uint32_t last_wake_ms = osKernelGetTickCount();

    for (;;) {
        VisionFrame_t frame = {};
        if (Communication_GetLatestVisionFrame(&frame, 0U)) {
            qd_controller.updateVisionRaw(frame);
        }

        BallStateEstimate_t state = {};
        if (qd_controller.updateBallStateEstimator(osKernelGetTickCount(), &state)) {
            PublishLatestState(state);
        } else {
            BallStateStoreLatest(&state);
        }

        osDelayUntil(last_wake_ms + kBallStatePeriodMs);
        last_wake_ms += kBallStatePeriodMs;
    }
}
