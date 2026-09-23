#include "cmsis_os.h"
#include "DebugCommand.h"
#include "QD4310.h"
#include "BallBeamController.h"
#include "BallStateEstimate.h"
#include "CommunicationTask.h"
#include "Serial.h"
#include "VisionFrame.h"

#include <cmath>
#include <cstdlib>
#include <cstring>

extern BallBeamController qd_controller;

namespace {

constexpr uint16_t kLineBufferSize = 96U;
constexpr float kDegToRad = 0.0174532925f;
constexpr float kRadToDeg = 57.2957795f;
constexpr uint32_t kControlCsvPeriodMs = 5U;

enum class CsvMode : uint8_t {
    Vision,
    Control,
    Off,
};

char line_buffer[kLineBufferSize] = {};
uint16_t line_length = 0U;
float debug_current = 0.0f;
float current_step = 0.05f;
uint32_t last_csv_ms = 0U;
CsvMode csv_mode = CsvMode::Control;
float last_debug_x_cm = 0.0f;
bool has_last_debug_x = false;

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

bool ParseThreeFloats(float *a, float *b, float *c)
{
    return ParseFloat(NextToken(), a) && ParseFloat(NextToken(), b) && ParseFloat(NextToken(), c);
}

bool ParseFourFloats(float *a, float *b, float *c, float *d)
{
    return ParseThreeFloats(a, b, c) && ParseFloat(NextToken(), d);
}

bool ParseThreeOrFourFloats(float *a, float *b, float *c, float *d)
{
    if (!ParseThreeFloats(a, b, c)) {
        return false;
    }
    char *optional = NextToken();
    if (optional == nullptr) {
        *d = 0.0f;
        return true;
    }
    return ParseFloat(optional, d);
}

void PrintFixed2(const char *prefix, float value, const char *suffix)
{
    if (!std::isfinite(value)) {
        Serial_Printf("%s0.00%s", prefix, suffix);
        return;
    }

    int32_t scaled = static_cast<int32_t>(std::lround(value * 100.0f));
    const char *sign = "";
    if (scaled < 0) {
        sign = "-";
        scaled = -scaled;
    }

    Serial_Printf("%s%s%ld.%02ld%s", prefix, sign, scaled / 100L, scaled % 100L, suffix);
}

void PrintCsvSample()
{
    BallStateEstimate_t state = {};
    const bool has_state = BallStateGetLatest(&state);
    if (!has_state) {
        state.raw_x_cm = qd_controller.getBallX();
        state.raw_vx_cm_s = qd_controller.getBallVx();
        state.filtered_x_cm = qd_controller.getEstimatedBallX();
        state.x_cm = qd_controller.getEstimatedBallX();
        state.vx_cm_s = qd_controller.getEstimatedBallVx();
        state.valid = 0U;
        state.vision_seq = qd_controller.getVisionSeq();
        const uint32_t now_ms = HAL_GetTick();
        const uint32_t last_vision_tick = qd_controller.getLastVisionTick();
        state.vision_age_ms = (last_vision_tick == 0U) ? 9999U : (now_ms - last_vision_tick);
    }
    last_debug_x_cm = state.x_cm;
    has_last_debug_x = true;

    PrintFixed2("", state.x_cm, ",");
    PrintFixed2("", qd_controller.getBallTarget(), ",");
    PrintFixed2("", state.vx_cm_s, ",");
    PrintFixed2("", qd_controller.motor_angle * kRadToDeg, ",");
    PrintFixed2("", qd_controller.getBallAngleCommand() * kRadToDeg, ",");
    PrintFixed2("", qd_controller.getBallBrakePOffsetDeg(), ",");
    PrintFixed2("", qd_controller.getBallTerminalOffsetDeg(), ",");
    Serial_Printf("%u,%u,%u,%u,%u,%lu\r\n",
                  qd_controller.isBallBrakePActive() ? 1U : 0U,
                  qd_controller.isBallTerminalPushActive() ? 1U : 0U,
                  qd_controller.isBallTerminalTrimActive() ? 1U : 0U,
                  qd_controller.isBallTerminalBrakeGateActive() ? 1U : 0U,
                  static_cast<unsigned int>(qd_controller.getBallSequenceStage()),
                  static_cast<unsigned long>(state.vision_age_ms));
}

void PrintVisionCsvSample(const VisionFrame_t *frame, const bool has_frame)
{
    BallStateEstimate_t state = {};
    const bool has_state = BallStateGetLatest(&state) != 0U;
    const uint32_t now_ms = HAL_GetTick();
    const uint32_t rx_age_ms = has_frame ? (now_ms - frame->rx_tick_ms) : 9999U;

    // Fixed 5 ms diagnostic row. Positions and velocity use 0.01 cm units
    // on the wire to keep USART6/115200 below its previous CSV bandwidth.
    // V,stm32_ms,rx_seq,pi_time_ms,tracking_valid,rx_age_ms,
    // packet_x_001cm,estimate_valid,estimated_x_001cm,
    // estimated_vx_001cms,valid_vision_age_ms
    Serial_Printf("V,%lu,%u,%lu,%u,%lu,%ld,%u,%ld,%ld,%lu\r\n",
                  static_cast<unsigned long>(now_ms),
                  has_frame ? static_cast<unsigned int>(frame->seq) : 0U,
                  has_frame ? static_cast<unsigned long>(frame->pi_time_ms) : 0UL,
                  (has_frame && (frame->tracking_valid != 0U)) ? 1U : 0U,
                  static_cast<unsigned long>(rx_age_ms),
                  has_frame ? static_cast<long>(frame->ball_pos_001cm) : 0L,
                  (has_state && (state.valid != 0U)) ? 1U : 0U,
                  static_cast<long>(std::lround((has_state ? state.x_cm : 0.0f) * 100.0f)),
                  static_cast<long>(std::lround((has_state ? state.vx_cm_s : 0.0f) * 100.0f)),
                  static_cast<unsigned long>(has_state ? state.vision_age_ms : 9999U));
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
    if (osMessageQueuePut(DebugCommandHandle, &command, 0U, 20U) != osOK) {
        Serial_Printf("debug command queue full\r\n");
    }
}

void ExecuteLine(char *line)
{
    char *cmd = std::strtok(line, " \t");

    if (cmd == nullptr) {
        return;
    }

    if ((std::strcmp(cmd, "enable") == 0) || (std::strcmp(cmd, "en") == 0)) {
        PostCommand(DEBUG_CMD_ENABLE);
    } else if ((std::strcmp(cmd, "disable") == 0) || (std::strcmp(cmd, "dis") == 0)) {
        debug_current = 0.0f;
        PostCommand(DEBUG_CMD_DISABLE);
    } else if (std::strcmp(cmd, "start") == 0) {
        PostCommand(DEBUG_CMD_START);
    } else if (std::strcmp(cmd, "stop") == 0) {
        debug_current = 0.0f;
        PostCommand(DEBUG_CMD_STOP);
    } else if ((std::strcmp(cmd, "current") == 0) || (std::strcmp(cmd, "cur") == 0)) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            debug_current = value;
            PostCommand(DEBUG_CMD_SET_CURRENT, debug_current);
        }
    } else if (std::strcmp(cmd, "+") == 0) {
        debug_current += current_step;
        PostCommand(DEBUG_CMD_SET_CURRENT, debug_current);
    } else if (std::strcmp(cmd, "-") == 0) {
        debug_current -= current_step;
        PostCommand(DEBUG_CMD_SET_CURRENT, debug_current);
    } else if ((std::strcmp(cmd, "zero") == 0) || (std::strcmp(cmd, "0") == 0)) {
        debug_current = 0.0f;
        PostCommand(DEBUG_CMD_SET_CURRENT, 0.0f);
    } else if (std::strcmp(cmd, "speed") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_SET_SPEED, value);
        }
    } else if (std::strcmp(cmd, "angle") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_SET_ANGLE, value * kDegToRad);
        }
    } else if (std::strcmp(cmd, "step") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_SET_STEP_ANGLE, value * kDegToRad);
        }
    } else if (std::strcmp(cmd, "lowspeed") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_SET_LOW_SPEED, value);
        }
    } else if (std::strcmp(cmd, "spid") == 0) {
        float kp = 0.0f;
        float ki = 0.0f;
        float kd = 0.0f;
        if (ParseThreeFloats(&kp, &ki, &kd)) {
            PostCommand(DEBUG_CMD_SET_SPEED_PID, kp, ki, kd);
        }
    } else if (std::strcmp(cmd, "apid") == 0) {
        float kp = 0.0f;
        float ki = 0.0f;
        float kd = 0.0f;
        if (ParseThreeFloats(&kp, &ki, &kd)) {
            PostCommand(DEBUG_CMD_SET_ANGLE_PID, kp, ki, kd);
        }
    } else if (std::strcmp(cmd, "ilimit") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_SET_CURRENT_LIMIT, value);
        }
    } else if (std::strcmp(cmd, "alimit") == 0) {
        char *token = NextToken();
        if ((token != nullptr) && (std::strcmp(token, "off") == 0)) {
            PostCommand(DEBUG_CMD_DISABLE_ANGLE_LIMIT);
        } else {
            float min_angle = 0.0f;
            float max_angle = 0.0f;
            if (ParseFloat(token, &min_angle) && ParseFloat(NextToken(), &max_angle)) {
                PostCommand(DEBUG_CMD_SET_ANGLE_LIMIT, min_angle * kDegToRad, max_angle * kDegToRad);
            }
        }
    } else if (std::strcmp(cmd, "arate") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_SET_ANGLE_RATE_LIMIT, value * kDegToRad);
        }
    } else if (std::strcmp(cmd, "adead") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_SET_ANGLE_CMD_DEADBAND, value);
        }
    } else if (std::strcmp(cmd, "ball") == 0) {
        char *token = NextToken();
        if ((token != nullptr) && (std::strcmp(token, "on") == 0)) {
            PostCommand(DEBUG_CMD_BALL_ENABLE);
        } else if ((token != nullptr) && (std::strcmp(token, "off") == 0)) {
            PostCommand(DEBUG_CMD_BALL_DISABLE);
        }
    } else if (std::strcmp(cmd, "bt") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_BALL_SET_TARGET, value);
        }
    } else if (std::strcmp(cmd, "bseq") == 0) {
        float first = 0.0f;
        float second = 0.0f;
        float turn_window = 0.5f;
        float turn_v = 0.6f;
        if (ParseFloat(NextToken(), &first) && ParseFloat(NextToken(), &second)) {
            char *third = NextToken();
            if (third != nullptr) {
                ParseFloat(third, &turn_window);
                char *fourth = NextToken();
                if (fourth != nullptr) {
                    ParseFloat(fourth, &turn_v);
                }
            }
            PostCommand(DEBUG_CMD_BALL_START_SEQUENCE, first, second, turn_window, turn_v);
        }
    } else if (std::strcmp(cmd, "task") == 0) {
        char *task = NextToken();
        if ((task != nullptr) && (std::strcmp(task, "init") == 0)) {
            PostCommand(DEBUG_CMD_BALL_INITIALIZE_TASK);
        } else if ((task != nullptr) && (std::strcmp(task, "1") == 0)) {
            PostCommand(DEBUG_CMD_BALL_START_TASK, 1.0f);
        } else if ((task != nullptr) &&
                   ((std::strcmp(task, "stop") == 0) || (std::strcmp(task, "0") == 0))) {
            PostCommand(DEBUG_CMD_BALL_STOP_TASK);
        } else if ((task != nullptr) && (std::strcmp(task, "status") == 0)) {
            Serial_Printf("task=%u active=%u stage=%u\r\n",
                          static_cast<unsigned int>(qd_controller.getActiveTask()),
                          qd_controller.isTaskActive() ? 1U : 0U,
                          static_cast<unsigned int>(qd_controller.getBallSequenceStage()));
        }
    } else if (std::strcmp(cmd, "task1") == 0) {
        PostCommand(DEBUG_CMD_BALL_START_TASK, 1.0f);
    } else if (std::strcmp(cmd, "ba") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_BALL_SET_BALANCE_ANGLE, value * kDegToRad);
        }
    } else if (std::strcmp(cmd, "bgain") == 0) {
        float kp = 0.0f;
        float ki = 0.0f;
        float kd = 0.0f;
        if (ParseFloat(NextToken(), &kp) && ParseFloat(NextToken(), &ki)) {
            char *third = NextToken();
            if (third != nullptr) {
                if (ParseFloat(third, &kd)) {
                    PostCommand(DEBUG_CMD_BALL_SET_GAINS, kp, ki, kd);
                }
            } else {
                PostCommand(DEBUG_CMD_BALL_SET_GAINS, kp, 0.0f, ki);
            }
        }
    } else if (std::strcmp(cmd, "bff") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_BALL_SET_FEEDFORWARD, value);
        }
    } else if (std::strcmp(cmd, "bff2") == 0) {
        float pos_value = 0.0f;
        float neg_value = 0.0f;
        if (ParseFloat(NextToken(), &pos_value) && ParseFloat(NextToken(), &neg_value)) {
            PostCommand(DEBUG_CMD_BALL_SET_FEEDFORWARD_SPLIT, pos_value, neg_value);
        }
    } else if (std::strcmp(cmd, "bw") == 0) {
        float far_error = 0.0f;
        float near_error = 0.0f;
        float min_weight = 0.0f;
        if (ParseThreeFloats(&far_error, &near_error, &min_weight)) {
            PostCommand(DEBUG_CMD_BALL_SET_VISION_WEIGHT, far_error, near_error, min_weight);
        }
    } else if (std::strcmp(cmd, "bdw") == 0) {
        float far_error = 0.0f;
        float near_error = 0.0f;
        float min_weight = 0.0f;
        if (ParseThreeFloats(&far_error, &near_error, &min_weight)) {
            PostCommand(DEBUG_CMD_BALL_SET_D_WEIGHT, far_error, near_error, min_weight);
        }
    } else if (std::strcmp(cmd, "bbp") == 0) {
        float kp = 0.0f;
        float margin = 0.0f;
        float max_angle = 0.0f;
        float dist = 0.0f;
        if (ParseFourFloats(&kp, &margin, &max_angle, &dist)) {
            PostCommand(DEBUG_CMD_BALL_SET_BRAKE_P, kp, margin, max_angle, dist);
        }
    } else if (std::strcmp(cmd, "bbpd") == 0) {
        float kp = 0.0f;
        float margin = 0.0f;
        float max_angle = 0.0f;
        float dist = 0.0f;
        if (ParseFourFloats(&kp, &margin, &max_angle, &dist)) {
            PostCommand(DEBUG_CMD_BALL_SET_BRAKE_P_LONG, kp, margin, max_angle, dist);
        }
    } else if (std::strcmp(cmd, "bbpv") == 0) {
        float kp = 0.0f;
        float target_v = 0.0f;
        float max_angle = 0.0f;
        if (ParseThreeFloats(&kp, &target_v, &max_angle)) {
            PostCommand(DEBUG_CMD_BALL_SET_BRAKE_P_SPEED, kp, target_v, max_angle);
        }
    } else if (std::strcmp(cmd, "bbpn") == 0) {
        float max_angle = 0.0f;
        if (ParseFloat(NextToken(), &max_angle)) {
            PostCommand(DEBUG_CMD_BALL_SET_BRAKE_P_NEGATIVE_MAX, max_angle);
        }
    } else if (std::strcmp(cmd, "bterm") == 0) {
        float x_window = 0.0f;
        float vx_window = 0.0f;
        if (ParseFloat(NextToken(), &x_window) && ParseFloat(NextToken(), &vx_window)) {
            PostCommand(DEBUG_CMD_BALL_SET_TERMINAL_BRAKE_GATE, x_window, vx_window);
        }
    } else if (std::strcmp(cmd, "bpush") == 0) {
        float window = 0.0f;
        float vx_window = 0.0f;
        float push_angle = 0.0f;
        float unused_max_angle = 0.0f;
        if (ParseThreeOrFourFloats(&window, &vx_window, &push_angle, &unused_max_angle)) {
            PostCommand(DEBUG_CMD_BALL_SET_TERMINAL_PUSH, window, vx_window, push_angle, unused_max_angle);
        }
    } else if ((std::strcmp(cmd, "bpushp") == 0) || (std::strcmp(cmd, "bpushpos") == 0)) {
        float window = 0.0f;
        float vx_window = 0.0f;
        float push_angle = 0.0f;
        float unused_max_angle = 0.0f;
        if (ParseThreeOrFourFloats(&window, &vx_window, &push_angle, &unused_max_angle)) {
            PostCommand(DEBUG_CMD_BALL_SET_TERMINAL_PUSH_POSITIVE, window, vx_window, push_angle, unused_max_angle);
        }
    } else if ((std::strcmp(cmd, "bpushm") == 0) || (std::strcmp(cmd, "bpushneg") == 0)) {
        float window = 0.0f;
        float vx_window = 0.0f;
        float push_angle = 0.0f;
        float unused_max_angle = 0.0f;
        if (ParseThreeOrFourFloats(&window, &vx_window, &push_angle, &unused_max_angle)) {
            PostCommand(DEBUG_CMD_BALL_SET_TERMINAL_PUSH_NEGATIVE, window, vx_window, push_angle, unused_max_angle);
        }
    } else if (std::strcmp(cmd, "blimit") == 0) {
        float value = 0.0f;
        if (ParseFloat(NextToken(), &value)) {
            PostCommand(DEBUG_CMD_BALL_SET_ANGLE_LIMIT, value);
        }
    } else if (std::strcmp(cmd, "bdead") == 0) {
        float x = 0.0f;
        float vx = 0.0f;
        if (ParseFloat(NextToken(), &x) && ParseFloat(NextToken(), &vx)) {
            PostCommand(DEBUG_CMD_BALL_SET_DEADBAND, x, vx);
        }
    } else if (std::strcmp(cmd, "brate") == 0) {
        float period_ms = 0.0f;
        if (ParseFloat(NextToken(), &period_ms)) {
            PostCommand(DEBUG_CMD_BALL_SET_RATE, period_ms);
        }
    } else if (std::strcmp(cmd, "vf") == 0) {
        float x_alpha = 0.0f;
        float vx_alpha = 0.0f;
        float dx_deadband = 0.0f;
        if (ParseThreeFloats(&x_alpha, &vx_alpha, &dx_deadband)) {
            PostCommand(DEBUG_CMD_VISION_SET_FILTER, x_alpha, vx_alpha, dx_deadband);
        }
    } else if (std::strcmp(cmd, "vdead") == 0) {
        float deadband = 0.0f;
        float unused1 = 0.0f;
        float unused2 = 0.0f;
        if (ParseThreeFloats(&deadband, &unused1, &unused2)) {
            PostCommand(DEBUG_CMD_VISION_SET_MEASUREMENT_DEADBAND, deadband);
        }
    } else if (std::strcmp(cmd, "vf2") == 0) {
        float max_velocity = 0.0f;
        float interp_ms = 0.0f;
        float max_x_step = 0.0f;
        if (ParseThreeFloats(&max_velocity, &interp_ms, &max_x_step)) {
            PostCommand(DEBUG_CMD_VISION_SET_FILTER_LIMITS,
                        max_velocity,
                        interp_ms,
                        max_x_step);
        }
    } else if (std::strcmp(cmd, "vv") == 0) {
        float window_points = 0.0f;
        float min_dx_cm = 0.0f;
        float reverse_limit = 0.0f;
        if (ParseThreeFloats(&window_points, &min_dx_cm, &reverse_limit)) {
            PostCommand(DEBUG_CMD_VISION_SET_VELOCITY,
                        window_points,
                        min_dx_cm,
                        reverse_limit);
        }
    } else if (std::strcmp(cmd, "vp") == 0) {
        float sample_ms = 0.0f;
        float predict_ms = 0.0f;
        float predict_step = 0.0f;
        if (ParseThreeFloats(&sample_ms, &predict_ms, &predict_step)) {
            PostCommand(DEBUG_CMD_VISION_SET_PREDICTION,
                        sample_ms,
                        predict_ms,
                        predict_step);
        }
    } else if ((std::strcmp(cmd, "vablim") == 0) || (std::strcmp(cmd, "vclim") == 0)) {
        float max_step = 0.0f;
        if (ParseFloat(NextToken(), &max_step)) {
            PostCommand(DEBUG_CMD_VISION_SET_AB_CORRECTION_LIMIT, max_step);
        }
    } else if (std::strcmp(cmd, "csv") == 0) {
        char *mode = NextToken();
        if ((mode != nullptr) && (std::strcmp(mode, "vision") == 0)) {
            csv_mode = CsvMode::Vision;
            last_csv_ms = 0U;
            Serial_Printf("csv=vision\r\n");
        } else if ((mode != nullptr) && (std::strcmp(mode, "control") == 0)) {
            csv_mode = CsvMode::Control;
            last_csv_ms = 0U;
            Serial_Printf("csv=control\r\n");
        } else if ((mode != nullptr) && (std::strcmp(mode, "off") == 0)) {
            csv_mode = CsvMode::Off;
            Serial_Printf("csv=off\r\n");
        }
    } else if ((std::strcmp(cmd, "set_zeropoint") == 0) ||
               (std::strcmp(cmd, "zeropoint") == 0) ||
               (std::strcmp(cmd, "setzero") == 0)) {
        PostCommand(DEBUG_CMD_SET_ZERO_POINT);
    } else if ((std::strcmp(cmd, "clear_zeropoint") == 0) ||
               (std::strcmp(cmd, "zerooff") == 0)) {
        PostCommand(DEBUG_CMD_CLEAR_ZERO_POINT);
    }
}

void PushChar(uint8_t ch)
{
    if ((ch == '\r') || (ch == '\n')) {
        if (line_length > 0U) {
            line_buffer[line_length] = '\0';
            ExecuteLine(line_buffer);
            line_length = 0U;
        }
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
    }
}

} // namespace

extern "C" void DebugTask(void *argument)
{
    (void)argument;

    Serial_Init();

    for (;;) {
        uint8_t ch = 0U;

        while (Serial_GetRxByte(&ch)) {
            PushChar(ch);
        }

        if (Serial_GetRxOverflow()) {
            Serial_ClearRxOverflow();
        }

        const uint32_t now_ms = HAL_GetTick();
        if ((csv_mode == CsvMode::Control) &&
            ((now_ms - last_csv_ms) >= kControlCsvPeriodMs)) {
            PrintCsvSample();
            last_csv_ms = now_ms;
        } else if ((csv_mode == CsvMode::Vision) &&
                   ((now_ms - last_csv_ms) >= kControlCsvPeriodMs)) {
            VisionFrame_t frame = {};
            const bool has_frame = Communication_GetLatestVisionFrame(&frame, 0U);
            PrintVisionCsvSample(has_frame ? &frame : nullptr, has_frame);
            last_csv_ms = now_ms;
        }

        osDelay(1);
    }
}








