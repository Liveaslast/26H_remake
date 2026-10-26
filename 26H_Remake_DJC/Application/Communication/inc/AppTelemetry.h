#ifndef APP_TELEMETRY_H
#define APP_TELEMETRY_H

#include "PiProtocol.h"

// 汇总APP当前状态，返回待回传的物理量；不修改控制器，不分配帧序号、不拼装协议、不发送串口。
PiProtocol::TelemetrySample CollectAppTelemetry(uint32_t now_ms);

#endif
