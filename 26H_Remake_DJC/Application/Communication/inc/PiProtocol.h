#ifndef PI_PROTOCOL_H
#define PI_PROTOCOL_H

#include <stdint.h>
#include "VisionData.h"

enum { COMM_MODE_NONE = 0, COMM_MODE_RUN = 1, COMM_MODE_TUNING = 2 };
enum { PI_REQUEST_NONE = 0 };

// 模式请求的解码结果，不含线上帧头、编号和CRC。
typedef struct {
    uint16_t seq; // 对应0x06模式请求的序号，不是任务请求号。
    uint8_t mode;
} PiModeRequest_t;

#ifdef __cplusplus
namespace PiProtocol {

// 模式应答的业务字段；打包后才成为包含帧头和CRC的0x86字节帧。
struct ModeReply {
    uint16_t seq;
    uint8_t mode;
    uint8_t result; // 0成功，1失败。
};

// 帧类型编号
enum class FrameType : uint8_t {
    ModeRequest = 0x06,
    Run = 0x07,
    Tuning = 0x08,
    RunTelemetry = 0x84,
    TuningTelemetry = 0x85,
    ModeReply = 0x86,
};

// pi -> stm32 接收帧容器
struct RxFrame {
    uint8_t size = 0;
    uint8_t data[39] = {};
};

// stm32 -> pi 发送帧容器
struct TxFrame {
    uint16_t size = 0;
    uint8_t data[39] = {};
};

// pi -> stm32 RUN/TUNING 数据帧的解码结果存放容器；视觉和参数均已还原为物理量。
struct DecodedRunTuningData {
    uint8_t mode = COMM_MODE_NONE;
    VisionData_t vision = {}; // 统一视觉输入定义，seq为来源数据帧的序号。
    uint8_t task_id = 0;
    uint16_t request_seq = 0, revision = 0; // 一次任务请求号、一次参数更新版本。
    float kp = 0, ki = 0, kd = 0, target_v_cm_s = 0;
};

// 解码结果总容器：frame_type决定读取mode_request还是run_tuning；不是线上字节布局。
struct DecodedPiData {
    FrameType frame_type = FrameType::ModeRequest;
    PiModeRequest_t mode_request = {};
    DecodedRunTuningData run_tuning = {};
};


// 待打包的遥测物理量：cm、cm/s、度及MCU毫秒；编码器负责缩放和CRC。
struct TelemetrySample {
    uint8_t status = 0;
    uint16_t seq = 0;
    float x_cm = 0, target_x_cm = 0, vx_cm_s = 0;
    float angle_deg = 0, target_angle_deg = 0;
    uint8_t stage = 0;
    uint16_t vision_seq = 0;
    uint32_t vision_age_ms = 0;
    float control_x_cm = 0, control_v_cm_s = 0, target_v_cm_s = 0;
    uint32_t control_tick_ms = 0, stm32_time_ms = 0;
    uint16_t request_seq = 0, revision = 0;
};


bool DecodeFrame(const RxFrame& frame, DecodedPiData& input);
void PackModeReply(const ModeReply& reply, TxFrame& frame);
void PackRunTelemetry(const TelemetrySample& sample, TxFrame& frame);
void PackTuningTelemetry(const TelemetrySample& sample, TxFrame& frame);

// 帧提取器：从字节流中提取出完整的帧
class FrameExtractor {
public:
    void push(uint8_t byte);            // 把数据存入缓冲区
    bool next(RxFrame& frame);          // 编号、长度和CRC检查通过的完整字节帧
    void reset() { size_ = 0; }         // 重置缓冲区，丢弃所有数据
private:
    uint8_t buffer_[sizeof(RxFrame::data)] = {};
    uint16_t size_ = 0;
    void discard(uint16_t count);
};

} // namespace PiProtocol
#endif
#endif
