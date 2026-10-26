#include "BallStateTask.h"

#include "BallStateEstimate.h"
#include "BallStateEstimator.h"
#include "CommunicationTask.h"
#include "VisionData.h"

#include "FreeRTOS.h"
#include "cmsis_os.h"
#include "task.h"

namespace {

constexpr uint32_t kBallStatePeriodMs = 2U;
BallStateEstimate_t latest_ball_state = {};         // 球状态快照
bool has_ball_state = false;                        // 是否保存过快照，与快照内state.valid无关。
BallStateEstimator::Config estimator_config{};

// 保存最新快照
void StoreLatestState(const BallStateEstimate_t& state)
{
    taskENTER_CRITICAL();
    latest_ball_state = state;
    has_ball_state = true;
    taskEXIT_CRITICAL();
}

} // namespace

// 获取估计器配置
BallStateEstimator::Config BallStateGetEstimatorConfig()
{
    taskENTER_CRITICAL();
    const auto config = estimator_config;
    taskEXIT_CRITICAL();
    return config;
}

// 设置估计器配置
bool BallStateSetEstimatorConfig(const BallStateEstimator::Config& config)
{
    if (!BallStateEstimator::isConfigValid(config)) return false;
    taskENTER_CRITICAL();
    estimator_config = config;
    taskEXIT_CRITICAL();
    return true;
}

// 读取最新快照
extern "C" uint8_t BallStateGetLatest(BallStateEstimate_t *state)
{
    if (state == nullptr) {
        return 0U;
    }

    bool has_snapshot = false;
    taskENTER_CRITICAL();
    has_snapshot = has_ball_state;
    if (has_snapshot) {
        *state = latest_ball_state;
    }
    taskEXIT_CRITICAL();
    return has_snapshot ? 1U : 0U;
}

// 估计器只由本任务持有和更新；其它任务只读取最新结果。
extern "C" void BallStateTask(void *argument)
{
    (void)argument;

    BallStateEstimator estimator;
    uint32_t last_wake_ms = osKernelGetTickCount();

    for (;;) {
        estimator.configure(BallStateGetEstimatorConfig());
        VisionData_t vision_data = {};
        if (Communication_ReadLatestVisionData(&vision_data, 0U)) {
            estimator.saveVisionMeasurement(vision_data);                       // 更新估计器的视觉输入
        }

        BallStateEstimate_t state = {};
        estimator.updateEstimate(osKernelGetTickCount(), &state);                 // 生成本轮估计
        StoreLatestState(state);                                          // 有效或无效都保存，不保留第二条队列路径。

        osDelayUntil(last_wake_ms + kBallStatePeriodMs);                                    // 等待下一个调度周期
        last_wake_ms += kBallStatePeriodMs;
    }
}
