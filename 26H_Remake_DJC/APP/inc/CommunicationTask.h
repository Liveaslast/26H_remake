#ifndef COMMUNICATION_TASK_H
#define COMMUNICATION_TASK_H

#include <stdbool.h>
#include <stdint.h>
#include "VisionData.h"
#include "PiProtocol.h"

#ifdef __cplusplus
extern "C" {
#endif

// 供PiRequestHandler读取的任务号、请求号和调参参数，不包含视觉测量或串口字节。
typedef struct {
    uint32_t mode_generation; // 模式切换次数，执行器据此清除去重记录，避免新模式请求被当成重复请求。
    uint8_t mode;
    uint8_t task_id;
    uint16_t request_seq;
    uint16_t revision;
    float kp, ki, kd, target_v_cm_s;
} PiExecutionRequest_t;

typedef enum {
    PI_RESULT_TASK,
    PI_RESULT_PARAMETERS,
} PiResultKind_t;

// PiRequestHandler读取待处理的模式请求，返回true时内容已复制到*request。
bool Communication_ReadModeRequest(PiModeRequest_t *request);

// 复制最新执行请求，不删除数据；返回true仅表示取得请求，不表示已执行。
bool Communication_ReadExecutionRequest(PiExecutionRequest_t *request);

// 把最新视觉数据复制到*vision_data；返回true不代表识别有效，还要检查tracking_valid。
bool Communication_ReadLatestVisionData(VisionData_t *vision_data, uint32_t max_age_ms);

// APP把处理结果保存回通信模块，之后由通信任务打包发送；这里不直接发送串口。
void Communication_SaveModeResult(const PiModeRequest_t *request, uint8_t result);

// 只供GimbalTask中的PiRequestHandler同步回报，不能从其它任务异步回报。
void Communication_SaveExecutionResult(PiResultKind_t kind, uint16_t result_id, bool success);

// RTOS通信任务入口
void StartCommunicationTask(void *argument);

#ifdef __cplusplus
}
#endif

#endif
