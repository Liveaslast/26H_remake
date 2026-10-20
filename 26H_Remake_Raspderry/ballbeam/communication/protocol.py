"""Two operating modes, explicit frame layouts, CRC and unit conversion."""
"""
pi 与 stm32之间的通信协议：
    通信线程建立后：
        1. Pi -> STM32 模式请求帧：
            确认将要运行RUN模式还是TUNING模式：
                RUN: 该模式只负责上下位机互传球杆核心数据，是一个最小的可执行任务模式
                TUNING: 该模式上位机可把参数打包发送到下位机，改变下位机参数（TP：为啥不直接让电脑接个蓝牙直接改下位机参数？因为我没有蓝牙）
        2. STM32 -> Pi 模式请求回应帧：
            回应上位机目前下位机是否收到并确认模式请求帧，上位机收到回应帧后开始周期发送任务帧到下位机 
        3. Pi -> STM32 任务帧：周期传送
            1. 初始化任务是TASK 0,RUN模式或者TUNING模式都一样
            2. RUN或者TUNING的TASK ID都从0到15，且两个模式下的任务是独立
        4. STM32 -> PI 任务遥测帧： 周期传送
            把任务帧中任务ID（TASK ID)对应的任务所需要的数据回传到上位机
"""



from dataclasses import dataclass
from enum import IntEnum
import math
import struct
from types import SimpleNamespace

PI_SOF = 0xA5                    # pi -> stm32 帧头
STM32_SOF = 0x5A                 # stm32 -> pi 帧头
CMD_MODE_REQUEST = 0x06          # pi -> stm32 模式选择帧编号（RUN运行模式、TUNING调参模式）
CMD_RUN_MODE = 0x07              # pi -> stm32 运行模式帧编号
CMD_TUNING_MODE = 0x08           # pi -> stm32 调参模式帧编号
CMD_RUN_TELEMETRY = 0x84         # stm32 -> pi 运行模式遥测帧编号
CMD_TUNING_TELEMETRY = 0x85      # stm32 -> pi 调参模式遥测帧编号
CMD_MODE_REPLY = 0x86            # stm32 -> pi 模式选择回应帧编号

TASK_ID_INIT = 0                        # 两种模式共用的初始化任务编号：0
TUNING_TASK_VELOCITY = 1                # TUNING模式中的球速阶跃任务编号
REQUEST_SEQ_NONE = 0                    # 请求号为0时仅传输数据，不执行任务
FLAG_TRACKING_VALID = 1          # pi -> stm32 视觉帧有效标志
STATUS_TASK_RESULT = 1 << 3      # stm32 -> pi 第4位：当前任务请求已成功执行
STATUS_CONFIG_RESULT = 1 << 4    # stm32 -> pi 第5位：当前参数版本已成功应用（TUNING模式）


class Mode(IntEnum):
    NONE = 0
    RUN = 1
    TUNING = 2


@dataclass(frozen=True)
class ModeReply:
    mode: Mode
    seq: int
    result: int             # 0 success, 1 failure

## 将视觉小球速度环PID所需参数整理成一组返回值
@dataclass(frozen=True)
class VelocityParameters:
    kp: float = 0.5
    ki: float = 0.0
    kd: float = 0.0
    target_v_cm_s: float = 2.0

    def scaled(self):
        limits = ((self.kp, 4.0), (self.ki, 5.0), (self.kd, 0.2))
        if any(not math.isfinite(v) or not 0 <= v <= limit for v, limit in limits):
            raise ValueError("PID out of range: Kp 0..4, Ki 0..5, Kd 0..0.2")
        if not math.isfinite(self.target_v_cm_s) or not 1 <= abs(self.target_v_cm_s) <= 5:
            raise ValueError("target speed magnitude must be 1..5 cm/s")
        return (*(round(v * 10000) for v, _ in limits), round(self.target_v_cm_s * 100))


# 小段字节序；位置/速度: 0.01 为一个整数单位; PID: 0.0001 为一个整数单位.
MODE_REQUEST_FRAME = struct.Struct("<BBHBB")                    # pi -> stm32: A5, 06, seq, mode, CRC
MODE_REPLY_FRAME = struct.Struct("<BBHBBB")                     # stm32 -> pi: 5A, 86, seq, mode, result, CRC
PI_RUN_FRAME = struct.Struct("<BBBHiiIBHB")                    # pi -> stm32: A5, 07, flags, seq, x, v, time, task, request, CRC
PI_TUNING_FRAME = struct.Struct("<BBBHiiIBHiiiiHB")              # pi -> stm32: A5, 08, fields, PID, target, revision, CRC
CONTROL_FIELDS = "<BBBHhhhhhhhBBHHhhhII"                        # 运行遥测与调参遥测共用的控制数据布局
RUN_TELEMETRY_FRAME = struct.Struct(CONTROL_FIELDS + "HB")     # stm32 -> pi: 运行遥测帧数据布局
TUNING_TELEMETRY_FRAME = struct.Struct(CONTROL_FIELDS + "HHB")   # stm32 -> pi: 调参遥测帧数据布局
MCU_FRAME_SIZES = {                                             # stm32 -> pi: 帧长度定义
    CMD_RUN_TELEMETRY: RUN_TELEMETRY_FRAME.size,
    CMD_TUNING_TELEMETRY: TUNING_TELEMETRY_FRAME.size,
    CMD_MODE_REPLY: MODE_REPLY_FRAME.size,
}

## CRC8检测
def crc8(data: bytes, polynomial=0x07, init=0):
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ polynomial) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

"""
通用打包机：
    1.layout : 打包格式
        eg.MODE_REQUEST_FRAME 
    2.*fileds : 数据字段
        eg.PI_SOF, CMD_MODE_REQUEST, seq & 0xFFFF, mode
"""
def _pack(layout, *fields):
    body = layout.pack(*fields, 0)[:-1]
    return body + bytes((crc8(body),))

## pi -> stm32:模式请求帧打包机
def pack_mode_request(seq, mode):
    mode = Mode(mode)
    if mode == Mode.NONE:
        raise ValueError("choose run or tuning mode")
    return _pack(MODE_REQUEST_FRAME, PI_SOF, CMD_MODE_REQUEST, seq & 0xFFFF, mode)

## 将视觉数据整理成一组返回值
def _vision_fields(seq, pos_cm, vel_cm_s, valid, pi_time_ms, task_id, request_seq):
    if not 0 <= task_id <= 15:
        raise ValueError("task ID must fit in four bits")
    return (int(bool(valid)), seq & 0xFFFF, round(pos_cm * 100), round(vel_cm_s * 100),
            pi_time_ms & 0xFFFFFFFF, task_id, request_seq & 0xFFFF)

## pi -> stm32:运行帧打包机
def pack_run(seq, pos_cm, vel_cm_s, valid, *, pi_time_ms, task_id=0, request_seq=0):
    return _pack(PI_RUN_FRAME, PI_SOF, CMD_RUN_MODE,
                 *_vision_fields(seq, pos_cm, vel_cm_s, valid, pi_time_ms, task_id, request_seq))

## pi -> stm32:调参帧打包机
def pack_tuning(seq, pos_cm, vel_cm_s, valid, *, pi_time_ms, task_id=0, request_seq=0,
                      parameters=VelocityParameters(), revision=0):
    return _pack(PI_TUNING_FRAME, PI_SOF, CMD_TUNING_MODE,
                 *_vision_fields(seq, pos_cm, vel_cm_s, valid, pi_time_ms, task_id, request_seq),
                 *parameters.scaled(), revision & 0xFFFF)

## pi运行帧/调参帧解码器
def decode_pi_frame(frame):
    """Read exact transmitted fields for logging in either mode."""
    layout = PI_RUN_FRAME if len(frame) >= 2 and frame[1] == CMD_RUN_MODE else PI_TUNING_FRAME
    expected = CMD_RUN_MODE if layout is PI_RUN_FRAME else CMD_TUNING_MODE
    _validate(frame, layout, PI_SOF, expected)
    fields = layout.unpack(frame)
    _, _, flags, seq, x, v, timestamp, task, request = fields[:9]
    return SimpleNamespace(flags=flags, tracking_valid=bool(flags & FLAG_TRACKING_VALID),
                           seq=seq, position_001cm=x, velocity_001cms=v,
                           pi_time_ms=timestamp, task_id=task, request_seq=request,
                           mode=Mode.RUN if layout is PI_RUN_FRAME else Mode.TUNING)

## 帧检查器
def _validate(frame, layout, sof, command):
    if len(frame) != layout.size or frame[:2] != bytes((sof, command)):
        raise ValueError("frame header or length mismatch")
    if crc8(frame[:-1]) != frame[-1]:
        raise ValueError("frame CRC mismatch")

## stm32 -> pi：0x84/0x85:运行遥测帧/调参遥测帧解码器
def decode_telemetry(frame):
    command = frame[1] if len(frame) >= 2 else 0
    if command not in (CMD_RUN_TELEMETRY, CMD_TUNING_TELEMETRY):
        raise ValueError("not a telemetry frame")
    layout = RUN_TELEMETRY_FRAME if command == CMD_RUN_TELEMETRY else TUNING_TELEMETRY_FRAME
    _validate(frame, layout, STM32_SOF, command)
    fields = layout.unpack(frame)
    (_, _, status, seq, x, target_x, v, angle, target_angle, bbp, trim,
     flags, stage, vision_seq, age, control_x, control_v, target_v,
     control_tick, mcu_tick, request_seq) = fields[:21]
    revision = fields[21] if command == CMD_TUNING_TELEMETRY else None
    sample = SimpleNamespace(
        seq=seq, stm32_time_ms=mcu_tick, ab_x=x / 100, target_x=target_x / 100,
        ab_v=v / 100, angle=angle / 100, target_angle=target_angle / 100,
        bbp_deg=bbp / 100, trim_deg=trim / 100, bbp=flags & 1, bpush=(flags >> 1) & 1,
        btrim=(flags >> 2) & 1, bterm=(flags >> 3) & 1, seq_stage=stage,
        vision_seq=vision_seq, age_ms=age, control_x=control_x / 100,
        control_v=control_v / 100, target_v=target_v / 100, control_tick_ms=control_tick,
    )
    return SimpleNamespace(
        status=status, seq=seq, stm32_time_ms=mcu_tick, actual_angle_deg=sample.angle,
        sample=sample, mode=Mode.RUN if command == CMD_RUN_TELEMETRY else Mode.TUNING,
        request_seq=request_seq, revision=revision,
    )

## stm32 -> pi：总解码器
def decode_frame(frame):
    if len(frame) >= 2 and frame[1] == CMD_MODE_REPLY:
        _validate(frame, MODE_REPLY_FRAME, STM32_SOF, CMD_MODE_REPLY)
        _, _, seq, mode, result, _ = MODE_REPLY_FRAME.unpack(frame)
        if mode not in (Mode.RUN, Mode.TUNING) or result not in (0, 1):
            raise ValueError("invalid mode reply")
        return ModeReply(Mode(mode), seq, result)
    return decode_telemetry(frame)


class FrameDecoder:
    def __init__(self):
        self._buffer = bytearray()
        self.last_error = None

    def reset(self):
        self._buffer.clear()
        self.last_error = None

    def feed(self, data: bytes) -> list:
        self._buffer.extend(data)
        frames = []
        while self._buffer:
            if self._buffer[0] != STM32_SOF:
                del self._buffer[0]
                continue
            if len(self._buffer) < 2:
                break
            size = MCU_FRAME_SIZES.get(self._buffer[1])
            if size is None:
                del self._buffer[0]
                self.last_error = "unknown frame type"
                continue
            if len(self._buffer) < size:
                break
            try:
                frame = decode_frame(bytes(self._buffer[:size]))
            except ValueError as exc:
                del self._buffer[0]
                self.last_error = str(exc)
                continue
            del self._buffer[:size]
            self.last_error = None
            frames.append(frame)
        return frames
