#include "cmsis_os.h"
#include "DebugCommand.h"
#include "QD4310.h"
#include "BallBeamController.h"
#include "BallStateEstimate.h"
#include "CommunicationTask.h"
#include "Serial.h"
#include "VisionFrame.h"
#include "SystemID.h"

#include <cmath>
#include <cstdlib>
#include <cstring>

extern BallBeamController qd_controller;

namespace {

constexpr uint16_t kLineBufferSize = 96U;       // 下位机接收缓冲区大小
constexpr float kDegToRad = 0.0174532925f;      // 角度转弧度
constexpr float kRadToDeg = 57.2957795f;        // 弧度转角度
constexpr uint32_t kCsvPeriodMs = 5U;           // CSV打印周期

enum class CsvMode : uint8_t {                  // CSV打印模式枚举类型
    Vision,                                         // 视觉数据打印模式
    Control,                                        // 控制数据打印模式
    Sysid,                                          // 系统辨识数据打印模式(为未来MPC或者LQR控制器设计预留)
    Off,                                            // 关闭CSV打印
};

char line_buffer[kLineBufferSize] = {};         // 下位机接收缓冲区
uint16_t line_length = 0U;
bool discard_line = false;                     // 命令不完整时丢弃到下一个换行
uint32_t last_csv_ms = 0U;
CsvMode csv_mode = CsvMode::Control;            // 该变量用于记录当前的CSV打印模式，默认为控制数据打印模式

char *NextToken()
{
    return std::strtok(nullptr, " \t");
}

bool ParseFloat(char *token, float *value)
{
    if ((token == nullptr) || (value == nullptr)) {
        return false;
    }

    char *end = nullptr;
    const float parsed = std::strtof(token, &end);
    if ((end == token) || (*end != '\0')) {
        return false;
    }

    *value = parsed;
    return true;
}

void PrintCsvSample()                                   // 控制模式打印机
{
    BallStateEstimate_t state = {};                        // 该变量用于存储球杆系统状态
    if (BallStateGetLatest(&state) == 0U) {
        state.vision_age_ms = 9999U;
    }

    Serial_Printf("%ld,%ld,%ld,%ld,%ld,%ld,%ld,%u,%u,%u,%u,%u,%lu\r\n",
                static_cast<long>(std::lround(state.x_cm * 100.0f)),
                static_cast<long>(std::lround(qd_controller.getBallTarget() * 100.0f)),
                static_cast<long>(std::lround(state.vx_cm_s * 100.0f)),
                static_cast<long>(std::lround(qd_controller.motor_angle * kRadToDeg * 100.0f)),
                static_cast<long>(std::lround(qd_controller.getBallAngleCommand() * kRadToDeg * 100.0f)),
                static_cast<long>(std::lround(qd_controller.getBallBrakePOffsetDeg() * 100.0f)),
                static_cast<long>(std::lround(qd_controller.getBallTerminalOffsetDeg() * 100.0f)),
                qd_controller.isBallBrakePActive() ? 1U : 0U,
                qd_controller.isBallTerminalPushActive() ? 1U : 0U,
                qd_controller.isBallTerminalTrimActive() ? 1U : 0U,
                qd_controller.isBallTerminalBrakeGateActive() ? 1U : 0U,
                static_cast<unsigned int>(qd_controller.getBallSequenceStage()),
                static_cast<unsigned long>(state.vision_age_ms));
}

void PrintVisionCsvSample()                             // 视觉模式打印机
{
    VisionFrame_t frame = {};
    const bool has_frame = Communication_GetLatestVisionFrame(&frame, 0U);

    BallStateEstimate_t state = {};
    const bool has_state = BallStateGetLatest(&state) != 0U;
    const uint32_t now_ms = HAL_GetTick();
    const uint32_t rx_age_ms = has_frame ? (now_ms - frame.rx_tick_ms) : 9999U;

    // 固定5ms打印数据，位置和速度采用 0.01cm 为单位
    // 以降低 USART6（115200 波特率）的 CSV 数据传输带宽占用
    // CSV字段顺序
    // V,STM32时间,接收帧序号,树莓派时间戳,视觉跟踪有效标志,接收帧年龄,
    // 原始视觉位置,状态估计有效标志,估计位置,
    // 估计速度,有效视觉数据年龄。
    Serial_Printf("V,%lu,%u,%lu,%u,%lu,%ld,%u,%ld,%ld,%lu\r\n",
                  static_cast<unsigned long>(now_ms),
                  has_frame ? static_cast<unsigned int>(frame.seq) : 0U,
                  has_frame ? static_cast<unsigned long>(frame.pi_time_ms) : 0UL,
                  (has_frame && (frame.tracking_valid != 0U)) ? 1U : 0U,
                  static_cast<unsigned long>(rx_age_ms),
                  has_frame ? static_cast<long>(frame.ball_pos_001cm) : 0L,
                  (has_state && (state.valid != 0U)) ? 1U : 0U,
                  static_cast<long>(std::lround((has_state ? state.x_cm : 0.0f) * 100.0f)),
                  static_cast<long>(std::lround((has_state ? state.vx_cm_s : 0.0f) * 100.0f)),
                  static_cast<unsigned long>(has_state ? state.vision_age_ms : 9999U));
}

void PrintSysidSample()                                 // 系统辨识模式打印机
{
    SystemID_t sysid = {};
    BallStateEstimate_t state = {};
    const bool has_state = BallStateGetLatest(&state) != 0U;

    sysid.time_ms = HAL_GetTick();
    sysid.motor_angle_deg = qd_controller.motor_angle * kRadToDeg;
    sysid.estimated_x_cm = state.x_cm;
    sysid.estimated_v_cm_s = state.vx_cm_s;

    sysid.sysid_state_valid = (has_state && state.valid != 0U) ? 1U : 0U;

    Serial_Printf("S,%lu,%ld,%ld,%ld,%u\r\n",
              static_cast<unsigned long>(sysid.time_ms),
              static_cast<long>(std::lround(sysid.motor_angle_deg * 100.0f)),
              static_cast<long>(std::lround(sysid.estimated_x_cm * 100.0f)),
              static_cast<long>(std::lround(sysid.estimated_v_cm_s * 100.0f)),
              static_cast<unsigned int>(sysid.sysid_state_valid));

}


void PostCommand(DebugCommandId_t id,
                 float arg1 = 0.0f,
                 float arg2 = 0.0f,
                 float arg3 = 0.0f,
                 float arg4 = 0.0f)
{
    if (DebugCommandHandle == nullptr) {
        return;
    }

    DebugCommand_t command = {id, arg1, arg2, arg3, arg4};
    if ((osMessageQueuePut(DebugCommandHandle, &command, 0U, 0U) != osOK) &&
        (csv_mode == CsvMode::Off)) {
        Serial_Printf("debug command queue full\r\n");
    }
}

struct CommandSpec {
    const char *group;
    const char *action;
    uint8_t argument_count;
    DebugCommandId_t id;
    bool degrees_to_radians;
};

// Only commands with an active control/estimator consumer belong here.
// Task, CSV and zero-point commands are handled separately below.
constexpr CommandSpec kCommandSpecs[] = {                         // 调试命令表{命令组、命令名称、参数数量、命令ID、是否角度转弧度}
    {"motor", "enable", 0U, DEBUG_CMD_ENABLE, false},
    {"motor", "disable", 0U, DEBUG_CMD_DISABLE, false},
    {"motor", "start", 0U, DEBUG_CMD_START, false},
    {"motor", "stop", 0U, DEBUG_CMD_STOP, false},
    {"motor", "pid-speed", 3U, DEBUG_CMD_SET_SPEED_PID, false},
    {"motor", "pid-angle", 3U, DEBUG_CMD_SET_ANGLE_PID, false},
    {"motor", "target-current", 1U, DEBUG_CMD_SET_CURRENT, false},
    {"motor", "target-speed", 1U, DEBUG_CMD_SET_SPEED, false},
    {"motor", "target-angle", 1U, DEBUG_CMD_SET_ANGLE, true},
    {"motor", "target-step", 1U, DEBUG_CMD_SET_STEP_ANGLE, true},
    {"motor", "limit-current", 1U, DEBUG_CMD_SET_CURRENT_LIMIT, false},
    {"motor", "limit-angle", 2U, DEBUG_CMD_SET_ANGLE_LIMIT, true},
    {"motor", "limit-angle-off", 0U, DEBUG_CMD_DISABLE_ANGLE_LIMIT, false},
    {"motor", "limit-rate", 1U, DEBUG_CMD_SET_ANGLE_RATE_LIMIT, true},
    {"motor", "deadband-angle", 1U, DEBUG_CMD_SET_ANGLE_CMD_DEADBAND, false},
    {"ball", "enable", 0U, DEBUG_CMD_BALL_ENABLE, false},
    {"ball", "disable", 0U, DEBUG_CMD_BALL_DISABLE, false},
    {"ball", "pid-position", 3U, DEBUG_CMD_BALL_SET_POSITION_PID, false},
    {"ball", "pid-velocity", 3U, DEBUG_CMD_BALL_SET_VELOCITY_PID, false},
    {"ball", "target-position", 1U, DEBUG_CMD_BALL_SET_TARGET, false},
    {"ball", "target-speed", 1U, DEBUG_CMD_BALL_SET_TARGET_SPEED, false},
    {"ball", "balance-angle", 1U, DEBUG_CMD_BALL_SET_BALANCE_ANGLE, true},
    {"ball", "limit-angle", 1U, DEBUG_CMD_BALL_SET_ANGLE_LIMIT, false},
    {"ball", "limit-speed", 1U, DEBUG_CMD_BALL_SET_SPEED_LIMIT, false},
    {"ball", "feedforward", 2U, DEBUG_CMD_BALL_SET_FEEDFORWARD_SPLIT, false},
    {"ball", "rate", 1U, DEBUG_CMD_BALL_SET_RATE, false},
    {"ball", "deadband-position", 1U, DEBUG_CMD_BALL_SET_POSITION_DEADBAND, false},
    {"vision", "ab", 2U, DEBUG_CMD_VISION_SET_AB, false},
    {"vision", "deadband", 1U, DEBUG_CMD_VISION_SET_MEASUREMENT_DEADBAND, false},
    {"vision", "limit", 2U, DEBUG_CMD_VISION_SET_LIMITS, false},
    {"vision", "predict", 2U, DEBUG_CMD_VISION_SET_ACTIVE_PREDICTION, false},
};

const CommandSpec *FindCommand(const char *group, const char *action)
{
    if (group == nullptr || action == nullptr) {
        return nullptr;
    }
    for (const auto& spec : kCommandSpecs) {
        if (std::strcmp(group, spec.group) == 0 &&
            std::strcmp(action, spec.action) == 0) {
            return &spec;
        }
    }
    return nullptr;
}


bool ValidCommandArguments(const DebugCommandId_t id, const float *a)   // 对参数进行限制
{
    switch (id) {

    // 目标速度限制：1~5 cm/s（允许正负方向）
    case DEBUG_CMD_BALL_SET_TARGET_SPEED:
        return std::fabs(a[0]) >= 1.0f &&
               std::fabs(a[0]) <= 5.0f;

    // 小球目标位置限制：±10 cm
    case DEBUG_CMD_BALL_SET_TARGET:
        return std::fabs(a[0]) <= 10.0f;

    // 死区参数不得为负数
    case DEBUG_CMD_BALL_SET_POSITION_DEADBAND:
    case DEBUG_CMD_VISION_SET_MEASUREMENT_DEADBAND:
        return a[0] >= 0.0f;

    // 小球速度上限：0~12 cm/s（不允许为0）
    case DEBUG_CMD_BALL_SET_SPEED_LIMIT:
        return a[0] > 0.0f && a[0] <= 12.0f;

    // 视觉滤波系数限制：0~1
    case DEBUG_CMD_VISION_SET_AB:
        return a[0] >= 0.0f && a[0] <= 1.0f &&
               a[1] >= 0.0f && a[1] <= 1.0f;

    // 视觉限制参数必须大于0
    case DEBUG_CMD_VISION_SET_LIMITS:
        return a[0] > 0.0f && a[1] > 0.0f;

    // 视觉预测时间：0~80 ms，第二个参数非负
    case DEBUG_CMD_VISION_SET_ACTIVE_PREDICTION:
        return a[0] >= 0.0f && a[0] <= 80.0f &&
               a[1] >= 0.0f;

    // 其他命令（包括PID参数）不在此限制范围
    default:
        return true;
    }
}


void ExecuteLine(char *line)                              // 串口命令解析器
{
    const char *group = std::strtok(line, " \t");
    const char *action = NextToken();
    if (group == nullptr) {
        return;
    }

    if (std::strcmp(group, "csv") == 0) {                 // CSV打印模式解析
        if (action != nullptr && NextToken() == nullptr) {
            if (std::strcmp(action, "vision") == 0) csv_mode = CsvMode::Vision;
            else if (std::strcmp(action, "control") == 0) csv_mode = CsvMode::Control;
            else if (std::strcmp(action, "sysid") == 0) csv_mode = CsvMode::Sysid;
            else if (std::strcmp(action, "off") == 0) csv_mode = CsvMode::Off;
            else {
                if (csv_mode == CsvMode::Off) Serial_Printf("unknown csv mode\r\n");
                return;
            }
            last_csv_ms = 0U;
            if (csv_mode == CsvMode::Off) Serial_Printf("csv=%s\r\n", action);
        } else {
            if (csv_mode == CsvMode::Off) Serial_Printf("usage: csv vision|control|sysid|off\r\n");
        }
        return;
    }

    if (std::strcmp(group, "task") == 0) {                // 任务控制命令解析
        if (action == nullptr || NextToken() != nullptr) {
            if (csv_mode == CsvMode::Off) Serial_Printf("usage: task init|1|stop|status\r\n");
        } else if (std::strcmp(action, "init") == 0) {
            PostCommand(DEBUG_CMD_BALL_INITIALIZE_TASK);
        } else if (std::strcmp(action, "1") == 0) {
            PostCommand(DEBUG_CMD_BALL_START_TASK, 1.0f);
        } else if (std::strcmp(action, "stop") == 0) {
            PostCommand(DEBUG_CMD_BALL_STOP_TASK);
        } else if (std::strcmp(action, "status") == 0) {
            if (csv_mode == CsvMode::Off) {
                Serial_Printf("task=%u active=%u stage=%u\r\n",
                    static_cast<unsigned int>(qd_controller.getActiveTask()),
                    qd_controller.isTaskActive() ? 1U : 0U,
                    static_cast<unsigned int>(qd_controller.getBallSequenceStage()));
            }
        } else {
            if (csv_mode == CsvMode::Off) Serial_Printf("unknown task command\r\n");
        }
        return;
    }

    if (std::strcmp(group, "zero") == 0) {                // 零点设置命令解析
        if (action == nullptr || NextToken() != nullptr) {
            if (csv_mode == CsvMode::Off) Serial_Printf("usage: zero set|clear\r\n");
        } else if (std::strcmp(action, "set") == 0) {
            PostCommand(DEBUG_CMD_SET_ZERO_POINT);
        } else if (std::strcmp(action, "clear") == 0) {
            PostCommand(DEBUG_CMD_CLEAR_ZERO_POINT);
        } else {
            if (csv_mode == CsvMode::Off) Serial_Printf("usage: zero set|clear\r\n");
        }
        return;
    }

    const CommandSpec *spec = FindCommand(group, action);
    if (spec == nullptr) {
        if (csv_mode == CsvMode::Off) Serial_Printf("unknown command\r\n");
        return;
    }
    float args[4] = {};
    for (uint8_t i = 0U; i < spec->argument_count; ++i) {
        if (!ParseFloat(NextToken(), &args[i]) || !std::isfinite(args[i])) {
            if (csv_mode == CsvMode::Off) Serial_Printf("invalid argument\r\n");
            return;
        }
    }
    if (NextToken() != nullptr) {
        if (csv_mode == CsvMode::Off) Serial_Printf("too many arguments\r\n");
        return;
    }
    if (!ValidCommandArguments(spec->id, args)) {
        if (csv_mode == CsvMode::Off) Serial_Printf("argument out of range\r\n");
        return;
    }
    if (spec->degrees_to_radians) {
        args[0] *= kDegToRad;
        if (spec->argument_count == 2U) args[1] *= kDegToRad;
    }
    PostCommand(spec->id, args[0], args[1], args[2], args[3]);
}

void PushChar(uint8_t ch)                           // 拼接缓冲区的字符形成字符串，遇到回车或换行符时，执行ExecuteLine函数
{
    if ((ch == '\r') || (ch == '\n')) {
        if (!discard_line && line_length > 0U) {
            line_buffer[line_length] = '\0';
            ExecuteLine(line_buffer);
        }
        line_length = 0U;
        discard_line = false;
        return;
    }

    if (discard_line) {
        return;
    }

    if ((ch == '\b') || (ch == 0x7FU)) {
        if (line_length > 0U) {
            line_length--;
        }
        return;
    }

    if (line_length < (kLineBufferSize - 1U)) {
        line_buffer[line_length++] = static_cast<char>(ch);
    } else {
        line_length = 0U;
        discard_line = true;
        if (csv_mode == CsvMode::Off) Serial_Printf("command too long\r\n");
    }
}

} // namespace

extern "C" void DebugTask(void *argument)                       // 调试任务函数
{
    (void)argument;

    Serial_Init();

    for (;;) {
        uint8_t ch = 0U;

        for (;;) {                                             // 读取现有字节，由PushChar按换行组装命令
            if (Serial_GetRxOverflow()) {
                Serial_DiscardRxBuffer();
                line_length = 0U;
                discard_line = true;
                if (csv_mode == CsvMode::Off) Serial_Printf("serial rx overflow; line discarded\r\n");
            }
            if (!Serial_GetRxByte(&ch)) {
                break;
            }
            PushChar(ch);
        }

        const uint32_t now_ms = HAL_GetTick();
        if ((csv_mode != CsvMode::Off) &&
            ((now_ms - last_csv_ms) >= kCsvPeriodMs)) {
            switch (csv_mode) {
            case CsvMode::Control: PrintCsvSample(); break;
            case CsvMode::Vision: PrintVisionCsvSample(); break;
            case CsvMode::Sysid: PrintSysidSample(); break;
            case CsvMode::Off: break;
            }
            last_csv_ms = now_ms;
        }

        osDelay(1);
    }
}








