#ifndef PI_REQUEST_HANDLER_H
#define PI_REQUEST_HANDLER_H

#include <stdint.h>

class BallBeamTasks;

// 具体任务号归执行层；通信层只搬运，不解释任务含义。
enum { PI_TASK_INIT = 0, PI_TUNING_TASK_VELOCITY = 1 };

// 读取Pi请求、调用对应业务并回报结果；每个模式代次内，相同请求和参数版本只处理一次。
class PiRequestHandler {
public:
    explicit PiRequestHandler(BallBeamTasks& ball_tasks) : ball_tasks_(ball_tasks) {}
    // 执行通信组件保存的模式、任务及参数请求，不在这里接收串口字节。
    void executePendingRequests();
private:
    void executeModeRequest();
    struct ParameterResult {
        uint8_t pi_task_id = 0;
        uint16_t revision = 0;
        bool succeeded = false;
        bool recorded = false;
    };
    BallBeamTasks& ball_tasks_;
    uint32_t last_mode_generation_ = 0;
    uint16_t last_task_request_seq_ = 0; // 0表示尚未执行任务请求，线上请求号0不启动任务。
    ParameterResult last_parameter_result_; // 参数版本与其处理结果放在一起。
};
#endif
