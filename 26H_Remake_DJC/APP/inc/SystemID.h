#ifndef SYSTEM_ID_H
#define SYSTEM_ID_H

#include <stdint.h>
#include "cmsis_os.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint32_t time_ms;           // MCU 本行采样时间
    float motor_angle_deg;      // 实际电机角：辨识输入
    float estimated_x_cm;       // 估计器输出位置
    float estimated_v_cm_s;     // 估计器输出速度
    uint8_t sysid_state_valid;  // 系统辨识状态有效标志
    // float tube_angle_deg;       // 水管角度 
} SystemID_t;

#ifdef __cplusplus
}
#endif

#endif
