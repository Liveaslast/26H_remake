#include "PiProtocol.h"

/*
通信协议
*/

#include <cmath>
#include <cstring>

namespace PiProtocol {
namespace {
constexpr uint8_t kPiSof = 0xA5;                            // pi -> stm32 帧头
constexpr uint8_t kMcuSof = 0x5A;                           // stm32 -> pi 帧头

// pi -> stm32 模式选择帧内容定义
struct __attribute__((packed)) ModeRequestPacket {          // cpp结构体
    uint8_t sof, cmd;
    uint16_t seq;
    uint8_t mode, crc;
};

// pi -> stm32 RUN模式帧内容定义
struct __attribute__((packed)) RunPacket {
    uint8_t sof, cmd, flags;
    uint16_t seq;
    int32_t x, v;
    uint32_t time;
    uint8_t task;
    uint16_t request;
    uint8_t crc;
};

// pi -> stm32 TUNING模式帧内容定义
struct __attribute__((packed)) TuningPacket {
    uint8_t sof, cmd, flags;
    uint16_t seq;
    int32_t x, v;
    uint32_t time;
    uint8_t task;
    uint16_t request;
    int32_t kp, ki, kd, target_v;
    uint16_t revision;
    uint8_t crc;
};

// stm32 -> pi 模式回复帧内容定义
struct __attribute__((packed)) ModeReplyPacket {
    uint8_t sof, cmd;
    uint16_t seq;
    uint8_t mode, result, crc;
};


// stm32 -> pi 遥测帧中的公共字段
struct __attribute__((packed)) ControlFields {
    uint8_t sof, cmd, status;
    uint16_t seq;
    int16_t x, target_x, v, angle, target_angle;
    uint8_t stage;
    uint16_t vision_seq, age;
    int16_t control_x, control_v, target_v;
    uint32_t control_time, mcu_time;
    uint16_t request;
};

// stm32 -> pi RUN模式遥测帧
struct __attribute__((packed)) RunTelemetryPacket {
    ControlFields data;
    uint8_t crc;
};

// stm32 -> pi TUNING模式遥测帧
struct __attribute__((packed)) TuningTelemetryPacket {
    ControlFields data;
    uint16_t revision;
    uint8_t crc;
};

static_assert(sizeof(ModeRequestPacket) == 6 && sizeof(ModeReplyPacket) == 7);
static_assert(sizeof(RunPacket) == 21 && sizeof(TuningPacket) == sizeof(RxFrame::data));
static_assert(sizeof(RunTelemetryPacket) == 37 && sizeof(TuningTelemetryPacket) == sizeof(TxFrame::data));

// CRC8计算
uint8_t Crc8(const uint8_t* data, uint16_t size)
{
    uint8_t crc = 0;
    for (uint16_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8; ++bit) {
            crc = (crc & 0x80U) ? static_cast<uint8_t>((crc << 1U) ^ 0x07U)
                               : static_cast<uint8_t>(crc << 1U);
        }
    }
    return crc;
}

// 计算帧大小
uint16_t PiFrameSize(uint8_t frame_type)
{
    switch (static_cast<FrameType>(frame_type)) {
    case FrameType::ModeRequest: return sizeof(ModeRequestPacket);
    case FrameType::Run: return sizeof(RunPacket);
    case FrameType::Tuning: return sizeof(TuningPacket);
    default: return 0;
    }
}

// 帧检查器：帧头、长度、CRC8
bool CheckPiFrame(const uint8_t* bytes, uint16_t size)
{
    if (size < 2U || bytes[0] != kPiSof) return false;
    const uint16_t expected = PiFrameSize(bytes[1]);
    return expected != 0U && size == expected &&
           bytes[size - 1U] == Crc8(bytes, size - 1U);
}

// 线上0.01整数单位转为物理量，不向APP暴露协议缩放。
float ScaleFromHundredths(int32_t value)
{
    return static_cast<float>(value) * 0.01f;
}

// RUN/TUNING共用字段解码：视觉状态、帧序号及任务请求帧共同字段解码器
template <typename Packet>
void DecodeVisionTaskFields(const Packet& packet, DecodedRunTuningData& data)
{
    data.vision.seq = packet.seq;
    data.vision.x_cm = ScaleFromHundredths(packet.x);
    data.vision.vx_cm_s = ScaleFromHundredths(packet.v);
    data.vision.pi_time_ms = packet.time;
    data.vision.tracking_valid = packet.flags & 1U;
    data.task_id = packet.task;
    data.request_seq = packet.request;
}

// float -> int16_t 缩放函数
int16_t ScaleToInt16Hundredths(float value)
{
    if (!std::isfinite(value)) return 0;
    const float scaled = value * 100.0f;
    if (scaled <= -32768.0f) return -32768;
    if (scaled >= 32767.0f) return 32767;
    return static_cast<int16_t>(std::lround(scaled));
}

template <typename Packet>
// stm32 -> pi 帧打包器
void PackPacket(Packet packet, TxFrame& frame)
{
    frame.size = sizeof(packet);
    std::memcpy(frame.data, &packet, sizeof(packet));
    frame.data[frame.size - 1U] = Crc8(frame.data, frame.size - 1U);
}

// pi -> stm32 模式请求帧解码器
void DecodeModeRequest(const RxFrame& frame, PiModeRequest_t& request)
{
    ModeRequestPacket packet;
    std::memcpy(&packet, frame.data, sizeof(packet));
    request = {packet.seq, packet.mode};
}

// pi -> stm32 RUN模式帧解码器
void DecodeRun(const RxFrame& frame, DecodedRunTuningData& data)
{
    RunPacket packet;
    std::memcpy(&packet, frame.data, sizeof(packet));
    data.mode = COMM_MODE_RUN;
    DecodeVisionTaskFields(packet, data);
}

// pi -> stm32 TUNING模式帧解码器
void DecodeTuning(const RxFrame& frame, DecodedRunTuningData& data)
{
    TuningPacket packet;
    std::memcpy(&packet, frame.data, sizeof(packet));
    data.mode = COMM_MODE_TUNING;
    DecodeVisionTaskFields(packet, data);
    data.kp = packet.kp * 0.0001f;
    data.ki = packet.ki * 0.0001f;
    data.kd = packet.kd * 0.0001f;
    data.target_v_cm_s = ScaleFromHundredths(packet.target_v);
    data.revision = packet.revision;
}

// stm32 -> pi 遥测帧公共字段编码器
ControlFields EncodeControlFields(FrameType frame_type, const TelemetrySample& sample)
{
    ControlFields fields{};
    fields.sof = kMcuSof;
    fields.cmd = static_cast<uint8_t>(frame_type);
    fields.status = sample.status;
    fields.seq = sample.seq;
    fields.x = ScaleToInt16Hundredths(sample.x_cm);
    fields.target_x = ScaleToInt16Hundredths(sample.target_x_cm);
    fields.v = ScaleToInt16Hundredths(sample.vx_cm_s);
    fields.angle = ScaleToInt16Hundredths(sample.angle_deg);
    fields.target_angle = ScaleToInt16Hundredths(sample.target_angle_deg);
    fields.stage = sample.stage;
    fields.vision_seq = sample.vision_seq;
    fields.age = static_cast<uint16_t>(sample.vision_age_ms > 65535U ? 65535U : sample.vision_age_ms);
    fields.control_x = ScaleToInt16Hundredths(sample.control_x_cm);
    fields.control_v = ScaleToInt16Hundredths(sample.control_v_cm_s);
    fields.target_v = ScaleToInt16Hundredths(sample.target_v_cm_s);
    fields.control_time = sample.control_tick_ms;
    fields.mcu_time = sample.stm32_time_ms;
    fields.request = sample.request_seq;
    return fields;
}

} // namespace

// 对外解码入口：先检查完整帧，再按编号解码
bool DecodeFrame(const RxFrame& frame, DecodedPiData& input)
{
    if (!CheckPiFrame(frame.data, frame.size)) return false;
    const FrameType frame_type = static_cast<FrameType>(frame.data[1]);
    if (frame_type != FrameType::ModeRequest && (frame.data[2] & ~1U) != 0U) return false;

    input = {};
    input.frame_type = frame_type;
    switch (frame_type) {           
    case FrameType::ModeRequest: DecodeModeRequest(frame, input.mode_request); break;
    case FrameType::Run: DecodeRun(frame, input.run_tuning); break;
    case FrameType::Tuning: DecodeTuning(frame, input.run_tuning); break;
    default: return false;
    }
    return true;
}

// stm32 -> pi 模式回应帧打包器
void PackModeReply(const ModeReply& reply, TxFrame& frame)
{
    PackPacket(ModeReplyPacket{kMcuSof, static_cast<uint8_t>(FrameType::ModeReply),
                              reply.seq, reply.mode, reply.result, 0}, frame);
}

// stm32 -> pi RUN模式遥测帧打包器
void PackRunTelemetry(const TelemetrySample& sample, TxFrame& frame)
{
    PackPacket(RunTelemetryPacket{EncodeControlFields(FrameType::RunTelemetry, sample), 0}, frame);
}

// stm32 -> pi TUNING模式遥测帧打包器
void PackTuningTelemetry(const TelemetrySample& sample, TxFrame& frame)
{
    PackPacket(TuningTelemetryPacket{EncodeControlFields(FrameType::TuningTelemetry, sample),
                                    sample.revision, 0}, frame);
}

// 字节流拆帧：管理半帧和重同步，不执行字段转换或业务动作。
void FrameExtractor::discard(uint16_t count)
{
    size_ -= count;
    std::memmove(buffer_, buffer_ + count, size_);
}

// 把数据放进缓冲区
void FrameExtractor::push(uint8_t byte)
{
    if (size_ == sizeof(buffer_)) discard(1);
    buffer_[size_++] = byte;
}

// 在缓冲区找出完整帧
bool FrameExtractor::next(RxFrame& frame)
{
    while (size_ != 0U) {
        if (buffer_[0] != kPiSof) {
            discard(1);
            continue;
        }
        if (size_ < 2U) return false;
        const uint16_t expected = PiFrameSize(buffer_[1]);
        if (expected != 0U) {
            if (size_ < expected) return false;
            if (CheckPiFrame(buffer_, expected)) {
                frame.size = static_cast<uint8_t>(expected);
                std::memcpy(frame.data, buffer_, expected);
                discard(expected);
                return true;
            }
        }
        discard(1);
    }
    return false;
}
} // namespace PiProtocol
