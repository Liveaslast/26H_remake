#include "CommunicationTask.h"

#include "FreeRTOS.h"
#include "cmsis_os.h"
#include "queue.h"
#include "task.h"
#include "usart.h"
#include "AppTelemetry.h"
#include "Serial.h"

namespace {
constexpr uint32_t kVisionTimeoutMs = 100U;
constexpr uint32_t kTelemetryPeriodMs = 20U;                // RUN和TUNING共用的遥测周期。
UART_HandleTypeDef *const kRaspberryUart = &huart1;

// DMA 缓冲区
uint8_t raspberry_rx_buffer[128] = {};                      // pi -> stm32 接收缓冲区
PiProtocol::FrameExtractor frame_extractor;                 // 协议层的帧提取器
PiProtocol::TxFrame tx_frame;                               // stm32 -> pi 帧容器
volatile bool tx_busy = false;                              // 发送区状态
osMessageQueueId_t rx_queue = nullptr;                      // 完整的接收字节帧 RxFrame
// 保存一条模式请求，等GimbalTask处理后，再由通信任务发送应答。
struct ModeExchange {
    // Idle：可以接收新请求；Requested：等待GimbalTask处理；ReplyReady：等待发送应答。
    enum class Stage { Idle, Requested, ReplyReady };
    PiModeRequest_t request = {};
    uint8_t result = 0;
    Stage stage = Stage::Idle;
} mode_exchange;
uint16_t telemetry_frame_seq = 0;                           // 遥测帧序号

// 通信任务保存下面的数据，其它任务通过本文件的获取接口读取；读写时避免任务中途切换。
uint8_t current_mode = COMM_MODE_NONE;                      // 当前模式
uint32_t mode_generation = 0;                               // 模式切换后让执行器清除去重记录，允许新模式重新使用相同请求号。
VisionData_t latest_vision_data = {};                       // 最新视觉数据
bool has_vision_data = false;                               // 当前是否保存了视觉数据，与tracking_valid无关。
PiExecutionRequest_t execution_request = {};                // 最新执行请求：任务及参数，不是闭环控制输出。
bool has_execution_request = false;                         // 是否保存过执行请求，不表示执行成功。
bool task_request_succeeded = false, parameters_applied = false;       // 任务请求成功、参数应用成功标志位
uint16_t handled_task_request_seq = 0, handled_parameter_revision = 0; // 已处理编号，不表示运动完成。

// 开启UART接收
void StartRaspberryUartReceive()
{
    if (HAL_UARTEx_ReceiveToIdle_DMA(kRaspberryUart, raspberry_rx_buffer,
                                    sizeof(raspberry_rx_buffer)) == HAL_OK) {
        __HAL_DMA_DISABLE_IT(kRaspberryUart->hdmarx, DMA_IT_HT);
    }
}

// 把打包好的帧交给DMA发送
bool Transmit()
{
    tx_busy = true;
    if (HAL_UART_Transmit_DMA(kRaspberryUart, tx_frame.data, tx_frame.size) == HAL_OK) return true;
    tx_busy = false;
    return false;
}

// 保存Pi发来的模式请求
bool RegisterModeRequest(const PiModeRequest_t& request)
{
    taskENTER_CRITICAL();
    const bool available = mode_exchange.stage == ModeExchange::Stage::Idle;
    if (available) {
        mode_exchange.request = request;
        mode_exchange.stage = ModeExchange::Stage::Requested;
    }
    taskEXIT_CRITICAL();
    return available;
}

// 保存Pi实际发来的视觉数据
void SaveVisionData(const VisionData_t& vision)
{
    latest_vision_data = vision;
    latest_vision_data.rx_tick_ms = HAL_GetTick();
    has_vision_data = true;
}

// 保存上位机发来的执行请求：任务号、请求号和调参参数；不包含视觉测量或串口字节。
void SaveExecutionRequest(const PiProtocol::DecodedRunTuningData& received)
{
    execution_request = {
        mode_generation, received.mode, received.task_id, received.request_seq, received.revision,
        received.kp, received.ki, received.kd, received.target_v_cm_s,
    };
    has_execution_request = true;
}

// 解码器
bool ProcessInput(const PiProtocol::RxFrame& frame)
{
    PiProtocol::DecodedPiData input;                                // 创建解码结果容器
    if (!PiProtocol::DecodeFrame(frame, input)) return true;        // 对帧进行解码,存放进input
    // 根据帧类型，保存请求帧或者任务帧所需要的数据。
    switch (input.frame_type) {
    case PiProtocol::FrameType::ModeRequest: {
        const auto& request = input.mode_request;
        if (request.mode != COMM_MODE_RUN && request.mode != COMM_MODE_TUNING) return true;
        return RegisterModeRequest(request);
    }
    case PiProtocol::FrameType::Run:
    case PiProtocol::FrameType::Tuning:
        // 两种任务帧都带视觉和任务请求；TUNING还带参数，RUN的参数由解码器置零。
        taskENTER_CRITICAL();
        if (input.run_tuning.mode == current_mode) {
            SaveVisionData(input.run_tuning.vision);               // BallStateTask读取。
            SaveExecutionRequest(input.run_tuning);                // PiRequestHandler读取。
        }
        taskEXIT_CRITICAL();
        break;
    default:
        break;
    }
    return true;
}

// 从队列取帧，调用ProcessInput；模式请求还不能保存时，留到下一轮，不跳过它处理后续帧。
void ProcessReceivedFrames()
{
    // 仅由唯一通信任务使用；跨循环保留尚未处理的那一帧，不是另一条消息队列。
    static PiProtocol::RxFrame pending_frame;
    static bool has_pending_frame = false;
    for (;;) {
        if (!has_pending_frame) {
            if (osMessageQueueGet(rx_queue, &pending_frame, nullptr, 0U) != osOK) return;
            has_pending_frame = true;
        }
        if (!ProcessInput(pending_frame)) return;
        has_pending_frame = false;
    }
}

// 读取电机角度、小球状态等APP数据，再补上遥测序号、通信状态和任务/参数结果编号。
PiProtocol::TelemetrySample CollectTelemetry()
{
    const uint32_t now = HAL_GetTick();
    auto sample = CollectAppTelemetry(now);
    sample.seq = telemetry_frame_seq++;
    taskENTER_CRITICAL();
    // 保留APP提供的电机状态，再加上视觉有效性和任务/参数结果。
    if (has_vision_data && latest_vision_data.tracking_valid &&
        now - latest_vision_data.rx_tick_ms <= kVisionTimeoutMs) sample.status |= 4U;
    if (task_request_succeeded && execution_request.request_seq == handled_task_request_seq) sample.status |= 8U;
    if (parameters_applied && execution_request.revision == handled_parameter_revision) sample.status |= 16U;
    sample.request_seq = handled_task_request_seq;
    sample.revision = handled_parameter_revision;
    taskEXIT_CRITICAL();
    return sample;
}

// GimbalTask处理模式请求后，把结果打包为0x86应答帧并启动DMA发送；发送忙时本轮跳过。
void SendModeReply()
{
    if (tx_busy) return;
    taskENTER_CRITICAL();
    const bool ready = mode_exchange.stage == ModeExchange::Stage::ReplyReady;
    const PiProtocol::ModeReply reply{mode_exchange.request.seq, mode_exchange.request.mode,
                                      mode_exchange.result};
    taskEXIT_CRITICAL();
    if (!ready) return;
    PiProtocol::PackModeReply(reply, tx_frame);
    if (Transmit()) {
        taskENTER_CRITICAL();
        mode_exchange.stage = ModeExchange::Stage::Idle;
        taskEXIT_CRITICAL();
    }
}

// 按当前模式打包遥测：RUN发0x84，TUNING发0x85；未选模式或发送忙时不发送。
void SendTelemetry()
{
    if (tx_busy) return;
    taskENTER_CRITICAL();
    const uint8_t mode = current_mode;
    taskEXIT_CRITICAL();
    switch (mode) {
    case COMM_MODE_RUN:
        PiProtocol::PackRunTelemetry(CollectTelemetry(), tx_frame);
        break;
    case COMM_MODE_TUNING:
        PiProtocol::PackTuningTelemetry(CollectTelemetry(), tx_frame);
        break;
    default:
        return;
    }
    Transmit();
}

// 遥测按时间发送，不是每收到一帧就回应一帧：两种模式均每20ms尝试发送。
void SendTelemetryWhenDue(uint32_t& last_telemetry_attempt_ms)
{
    const uint32_t now = HAL_GetTick();
    if (now - last_telemetry_attempt_ms < kTelemetryPeriodMs) return;
    SendTelemetry();
    last_telemetry_attempt_ms = now;
}
} // namespace

// PiRequestHandler读取尚未处理的模式请求；返回true时，请求内容已复制到*request。
extern "C" bool Communication_ReadModeRequest(PiModeRequest_t *request)
{
    if (request == nullptr) return false;
    taskENTER_CRITICAL();
    const bool requested = mode_exchange.stage == ModeExchange::Stage::Requested;
    if (requested) *request = mode_exchange.request;
    taskEXIT_CRITICAL();
    return requested;
}

// 保存模式请求结果
extern "C" void Communication_SaveModeResult(const PiModeRequest_t *request, uint8_t result)
{
    if (request == nullptr) return;
    taskENTER_CRITICAL();
    if (mode_exchange.stage == ModeExchange::Stage::Requested &&
        mode_exchange.request.seq == request->seq && mode_exchange.request.mode == request->mode) {
        if (result == 0U) {
            current_mode = request->mode;
            ++mode_generation;
            has_vision_data = has_execution_request = false;
            task_request_succeeded = parameters_applied = false;
        }
        mode_exchange.result = result;
        mode_exchange.stage = ModeExchange::Stage::ReplyReady;
    }
    taskEXIT_CRITICAL();
}

// PiRequestHandler读取最新的任务号和调参参数；返回true不代表请求已执行。
extern "C" bool Communication_ReadExecutionRequest(PiExecutionRequest_t *request)
{
    if (request == nullptr) return false;
    taskENTER_CRITICAL();
    const bool has_request = has_execution_request;
    if (has_request) *request = execution_request;
    taskEXIT_CRITICAL();
    return has_request;
}

// PiRequestHandler保存任务启动/初始化结果或参数应用结果，之后随遥测发给Pi。
// 只由GimbalTask中的PiRequestHandler同步调用；success不表示运动已完成。
extern "C" void Communication_SaveExecutionResult(PiResultKind_t kind, uint16_t result_id, bool success)
{
    taskENTER_CRITICAL();
    if (kind == PI_RESULT_PARAMETERS) {
        handled_parameter_revision = result_id;
        parameters_applied = success;
    } else if (kind == PI_RESULT_TASK) {
        handled_task_request_seq = result_id;
        task_request_succeeded = success;
    }
    taskEXIT_CRITICAL();
}

// 复制最新视觉数据到*vision_data；max_age_ms=0不检查数据年龄，否则超过指定毫秒数返回false。
// 返回true只表示取到了数据，还要看tracking_valid才能知道Pi是否识别到球。
extern "C" bool Communication_ReadLatestVisionData(VisionData_t *vision_data, uint32_t max_age_ms)
{
    if (vision_data == nullptr) return false;
    taskENTER_CRITICAL();
    const bool has_data = has_vision_data &&
        (max_age_ms == 0U || HAL_GetTick() - latest_vision_data.rx_tick_ms <= max_age_ms);
    if (has_data) *vision_data = latest_vision_data;
    taskEXIT_CRITICAL();
    return has_data;
}

// 启动时创建接收队列并开启DMA接收；循环中还会发送模式应答和周期遥测。
extern "C" void StartCommunicationTask(void *argument)
{
    (void)argument;
    rx_queue = osMessageQueueNew(8U, sizeof(PiProtocol::RxFrame), nullptr);
    if (rx_queue == nullptr) {
        for (;;) osDelay(100U);
    }
    StartRaspberryUartReceive();
    uint32_t last_telemetry_attempt_ms = HAL_GetTick();
    for (;;) {
        ProcessReceivedFrames();                                // 接收、解码、按帧类型保存，供APP读取。
        SendModeReply();                        // APP处理模式请求后，发送0x86应答。
        SendTelemetryWhenDue(last_telemetry_attempt_ms); // 读取APP状态，周期发送0x84或0x85。
        osDelay(1U);
    }
}


// 收到字节，提取完整帧，放入 rx_queue
extern "C" void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size)
{
    if (huart == kRaspberryUart) {
        BaseType_t woken = pdFALSE;
        PiProtocol::RxFrame frame;
        for (uint16_t i = 0; i < Size; ++i) {
            frame_extractor.push(raspberry_rx_buffer[i]);
            while (frame_extractor.next(frame)) {
                xQueueSendToBackFromISR(reinterpret_cast<QueueHandle_t>(rx_queue), &frame, &woken);
            }
        }
        portYIELD_FROM_ISR(woken);
        StartRaspberryUartReceive();
    }
}

// HAL通知DMA发送完成，解除tx_busy，允许通信任务发送下一帧。
extern "C" void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart == kRaspberryUart) tx_busy = false;
    Serial_OnTxCplt(huart);
}

// HAL通知串口出错，丢弃未收完整的帧、清除发送忙标记，再尝试开启接收。
extern "C" void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart == kRaspberryUart) {
        __HAL_UNLOCK(huart);
        frame_extractor.reset();
        tx_busy = false;
        StartRaspberryUartReceive();
    }
    Serial_OnError(huart);
}
