#include "PiRequestHandler.h"
#include "CommunicationTask.h"
#include "BallBeamTasks.h"
#include "BallStateTask.h"
#include "stm32f4xx_hal.h"

/*
上位机业务请求的入口
*/

namespace {
// 将线上参数交给速度测试业务，校验与是否允许应用由业务组件决定。
bool ApplyVelocityTestParameters(BallBeamTasks& ball_tasks, const PiExecutionRequest_t& request)
{
    return ball_tasks.setVelocityTestConfig(request.kp, request.ki, request.kd, request.target_v_cm_s);
}

bool InitializeBallTasks(BallBeamTasks& ball_tasks, const BallStateEstimate_t&, const VisionData_t&, uint32_t)
{
    ball_tasks.initializeTask();
    return true;
}

// 映射表指定球杆内部任务号，共用启动流程，不为每个任务写一份转发函数。
template<BallBeamTasks::TaskId task_id>
bool StartBallTask(BallBeamTasks& ball_tasks, const BallStateEstimate_t& ball_estimate,
                  const VisionData_t& latest_vision, uint32_t now_ms)
{
    return ball_tasks.startTask(task_id, ball_estimate, latest_vision, now_ms);
}

// 任务定义
struct PiTaskBinding {
    uint8_t mode;               // 模式： TUNING or RUN
    uint8_t pi_task_id;         // Pi线上任务ID，不是内部任务枚举
    bool (*start_task)(BallBeamTasks&, const BallStateEstimate_t&, const VisionData_t&, uint32_t); // 任务启动函数；业务自己检查输入
    bool (*apply_parameters)(BallBeamTasks&, const PiExecutionRequest_t&);     // 参数应用函数
};

// 任务登记表（新增任务在此登记）
constexpr PiTaskBinding kPiTaskBindings[] = {
    {COMM_MODE_RUN, PI_TASK_INIT, InitializeBallTasks, nullptr},
    {COMM_MODE_TUNING, PI_TASK_INIT, InitializeBallTasks, nullptr},
    {COMM_MODE_RUN, 1U, StartBallTask<BallBeamTasks::TaskId::Task1>, nullptr},
    {COMM_MODE_TUNING, PI_TUNING_TASK_VELOCITY,
     StartBallTask<BallBeamTasks::TaskId::VelocityStep>, ApplyVelocityTestParameters},
};

// 查找任务
const PiTaskBinding* FindPiTaskBinding(uint8_t mode, uint8_t pi_task_id)
{
    for (const auto& binding : kPiTaskBindings) {
        if (binding.mode == mode && binding.pi_task_id == pi_task_id) return &binding;
    }
    return nullptr;
}

}

void PiRequestHandler::executePendingRequests()
{
    executeModeRequest();
    PiExecutionRequest_t request = {};
    if (!Communication_ReadExecutionRequest(&request)) return;
    if (last_mode_generation_ != request.mode_generation) {
        last_mode_generation_ = request.mode_generation;
        last_task_request_seq_ = PI_REQUEST_NONE;
        last_parameter_result_ = {};
    }
    const PiTaskBinding* binding = FindPiTaskBinding(request.mode, request.task_id);
    // 参数更新与任务启动独立：新版本只应用一次，失败结果也保留到下一个版本。
    if (binding != nullptr && binding->apply_parameters != nullptr &&
        (!last_parameter_result_.recorded || last_parameter_result_.pi_task_id != request.task_id ||
         last_parameter_result_.revision != request.revision)) {
        const bool succeeded = binding->apply_parameters(ball_tasks_, request);
        last_parameter_result_ = ParameterResult{request.task_id, request.revision, succeeded, true};
        Communication_SaveExecutionResult(PI_RESULT_PARAMETERS, request.revision, succeeded);
    }
    // 即使task_id=0，纯数据包也不能执行电机初始化；必须带非零任务请求号。
    if (request.request_seq == PI_REQUEST_NONE ||
        last_task_request_seq_ == request.request_seq) return;

    // 需要参数的业务已在上面处理当前任务、当前版本，此处只读取该结果。
    bool success = false;
    if (binding != nullptr && (binding->apply_parameters == nullptr || last_parameter_result_.succeeded)) {
        BallStateEstimate_t ball_estimate = {};
        BallStateGetLatest(&ball_estimate);
        VisionData_t latest_vision = {};
        Communication_ReadLatestVisionData(&latest_vision, 0U);
        success = binding->start_task(ball_tasks_, ball_estimate, latest_vision, HAL_GetTick());
    }
    last_task_request_seq_ = request.request_seq;
    Communication_SaveExecutionResult(PI_RESULT_TASK, request.request_seq, success);
}

// 执行模式请求：
//     1 读取是否有新的模式请求
//     2 没有新的模式请求：返回
//     3 有新的模式请求：调用业务的模式切换准备入口，再保存处理结果；不等待机械到位
void PiRequestHandler::executeModeRequest()
{
    PiModeRequest_t request = {};
    if (!Communication_ReadModeRequest(&request)) return;
    ball_tasks_.stopForModeChange();
    Communication_SaveModeResult(&request, 0U);
}

