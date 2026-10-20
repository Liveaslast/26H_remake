#ifndef PI_CONTROL_H
#define PI_CONTROL_H

#include "BallBeamController.h"
#include "CommunicationTask.h"

// Execute each task request and parameter revision once per selected mode.
class PiControlExecutor {
public:
    explicit PiControlExecutor(BallBeamController& controller) : controller_(controller) {}
    void process();
private:
    void executeTask(const PiControlRequest_t& request);
    BallBeamController& controller_;
    uint32_t generation_ = 0;
    uint16_t last_request_ = 0, last_revision_ = 0;
    uint8_t parameter_task_id_ = PI_TASK_INIT;
    bool has_request_ = false, has_revision_ = false, parameters_ok_ = false;
};
#endif
