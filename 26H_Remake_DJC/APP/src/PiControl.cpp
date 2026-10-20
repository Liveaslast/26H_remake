#include "PiControl.h"
#include <cmath>

namespace {
bool ApplyVelocityParameters(BallBeamController& controller, const PiControlRequest_t& request)
{
    const bool valid = !controller.isTaskActive() &&
        request.kp >= 0 && request.kp <= 4 && request.ki >= 0 && request.ki <= 5 &&
        request.kd >= 0 && request.kd <= 0.2f &&
        std::fabs(request.target_v_cm_s) >= 1 && std::fabs(request.target_v_cm_s) <= 5;
    if (valid) {
        controller.setVelocityTestConfig(request.kp, request.ki, request.kd, request.target_v_cm_s);
    }
    return valid;
}

struct TaskBinding {
    uint8_t mode;
    uint8_t task_id;
    BallBeamController::TaskId action;
    bool (*apply_parameters)(BallBeamController&, const PiControlRequest_t&);
};

// Task IDs belong to a mode; the controller action need not share that number.
constexpr TaskBinding kTasks[] = {
    {COMM_MODE_RUN, 1U, BallBeamController::TaskId::Task1, nullptr},
    {COMM_MODE_TUNING, PI_TUNING_TASK_VELOCITY, BallBeamController::TaskId::VelocityStep, ApplyVelocityParameters},
};

const TaskBinding* FindTask(uint8_t mode, uint8_t task_id)
{
    for (const auto& task : kTasks) {
        if (task.mode == mode && task.task_id == task_id) return &task;
    }
    return nullptr;
}
}

void PiControlExecutor::process()
{
    PiControlRequest_t request = {};
    if (!Communication_GetControlRequest(&request)) return;
    if (request.mode != COMM_MODE_RUN && request.mode != COMM_MODE_TUNING) return;
    if (generation_ != request.generation) {
        generation_ = request.generation;
        has_request_ = has_revision_ = parameters_ok_ = false;
    }
    const TaskBinding* task = FindTask(request.mode, request.task_id);
    if (task != nullptr && task->apply_parameters != nullptr &&
        (!has_revision_ || parameter_task_id_ != request.task_id || last_revision_ != request.revision)) {
        parameters_ok_ = task->apply_parameters(controller_, request);
        has_revision_ = true;
        parameter_task_id_ = request.task_id;
        last_revision_ = request.revision;
        Communication_ReportSuccess(request.generation, true, request.revision, parameters_ok_);
    }
    // A data-only packet must never initialize the motor, even though task ID is 0.
    if (request.request_seq != PI_REQUEST_NONE &&
        (!has_request_ || last_request_ != request.request_seq)) {
        executeTask(request);
    }
}

void PiControlExecutor::executeTask(const PiControlRequest_t& request)
{
    bool success = false;
    if (request.task_id == PI_TASK_INIT) {
        if (!controller_.enabled) controller_.enable();
        controller_.start();
        controller_.initializeTask();
        success = true;
    } else {
        VisionFrame_t vision = {};
        const bool fresh = Communication_GetLatestVisionFrame(&vision, 100U) && vision.tracking_valid;
        const TaskBinding* task = FindTask(request.mode, request.task_id);
        const bool parameters_ready = task != nullptr && (task->apply_parameters == nullptr ||
            (has_revision_ && parameter_task_id_ == request.task_id &&
             last_revision_ == request.revision && parameters_ok_));
        if (fresh && parameters_ready) {
            if (!controller_.enabled) controller_.enable();
            controller_.start();
            success = controller_.startTask(task->action);
        }
    }
    has_request_ = true;
    last_request_ = request.request_seq;
    Communication_ReportSuccess(request.generation, false, request.request_seq, success);
}
