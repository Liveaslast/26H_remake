#ifndef VISION_DATA_H
#define VISION_DATA_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// 来自Pi的视觉数据，不含串口帧头、帧类型或CRC；位置/速度单位为cm、cm/s。
typedef struct {
    float x_cm;
    float vx_cm_s;
    uint8_t tracking_valid;
    uint16_t seq;
    uint32_t pi_time_ms;
    uint32_t rx_tick_ms; // 协议解码时为0，由通信层补充MCU接收处理时间。
} VisionData_t;

#ifdef __cplusplus
}

// 测量本身是否可用；接收时间是否过期由使用方按自己的时限判断。
inline bool IsVisionMeasurementUsable(const VisionData_t& data)
{
    return data.tracking_valid != 0U && data.x_cm >= -11.0f && data.x_cm <= 11.0f;
}
#endif

#endif
