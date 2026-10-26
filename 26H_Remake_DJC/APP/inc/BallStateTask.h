#ifndef BALL_STATE_TASK_H
#define BALL_STATE_TASK_H

#include "BallStateEstimate.h"

#ifdef __cplusplus
extern "C" {
#endif

void BallStateTask(void *argument);
// 返回是否取得估计记录；state.valid另行表示估计状态是否可用。
uint8_t BallStateGetLatest(BallStateEstimate_t *state);

#ifdef __cplusplus
}

#include "BallStateEstimator.h"
// 调试层读改配置；估计任务在下一轮采用，不跨任务直接修改估计器历史。
BallStateEstimator::Config BallStateGetEstimatorConfig();
bool BallStateSetEstimatorConfig(const BallStateEstimator::Config& config);
#endif

#endif
