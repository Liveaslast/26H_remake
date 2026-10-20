"""
这是通信层的客户端：
    应用程序使用通信功能的统一接口
"""

import math
import sys
from types import SimpleNamespace

from ..hardware.serial_config import SerialConfig
from .protocol import (
    Mode, VelocityParameters, STATUS_TASK_RESULT, STATUS_CONFIG_RESULT, TUNING_TASK_VELOCITY,
    decode_pi_frame, FrameDecoder,
)
from .session import CommunicationSession
from .transport import SerialTransport

## MCU串口通信客户端
class McuSerialClient:
    def __init__(self, port: str, baudrate: int, *,         # 创建客户端所需对象及初始状态
                 read_timeout_seconds: float, write_timeout_seconds: float) -> None:
        # 1. 创建通信组件
        self.config = SerialConfig(port, baudrate, read_timeout_seconds,        # 保存通信配置（端口、波特率、读取、写入超时时间）
                                   write_timeout_seconds)
        self.transport = SerialTransport(self.config)                           # 创建串口收发器
        self.decoder = FrameDecoder()                                           # 创建收帧解析器（从字节中找出帧并解码）
        self.session = CommunicationSession(                                    # 创建通信会话（后两个是回调函数
            self.transport, self.decoder, self._publish_telemetry, self._record_sent_frame,
        )
        # 2. 预留对外通知接口（回调函数）
        self.record_actual_angle = None                 # 当获取并解析遥测帧（不包含模式请求应答帧）后，把遥测帧中的角度保存
        self.record_control_sample = None               # 把遥测帧（。。。）中的控制数据保存成CSV格式，方便上位机分析或者scp至电脑
        self.record_sent_frame = None                   # 记录pi向stm32发送的帧，可以在上位机分析原始视觉数据或者与MCU回传的数据对照排除

        # 4. 初始化记录状态
        self.latest_telemetry = None                # 保存最新的下位机遥测
        self.visual_state_sent = False              # 判断成功写入串口的包，其视觉有效位是否为1

    @property
    def last_error(self):
        return (self.session.last_error or self.session.mode.last_error or self.session.sender.last_error
                or self.decoder.last_error or self.transport.last_error)

    @property
    def send_failures(self) -> int:
        return self.session.send_failures

    ## 打开串口、开启通信线程
    def start(self) -> None:
        if self.session.is_running:
            return
        self.latest_telemetry = None
        self.visual_state_sent = False
        self.transport.open()                       ## 打开串口
        try:
            self.session.start()                    ## 开启通信线程
        except Exception:
            self.transport.close()
            raise

    ## 停止通信线程、关闭串口
    def stop(self) -> None:
        self.session.stop()
        self.transport.close()

    ## 发送模式请求帧
    def select_mode(self, mode: Mode, *, timeout_seconds: float = 1.0) -> bool:
        """Confirm mode entry before any task/tuning data is transmitted."""
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("mode timeout must be positive")
        self.latest_telemetry = None
        self.visual_state_sent = False

        # 请求通信线程进入“模式请求模式”（请求RUN模式还是TUNING模式）
        selected = self.session.call("mode", (Mode(mode), timeout_seconds))
        self.latest_telemetry = None
        return selected

    ## 发送任务id请求到通信会话
    def request_task(self, task_id: int) -> int:
        """Set a task request in subsequent data packets; return its request number."""
        return self.session.call("task", task_id)

    ## 设置TUNING: TASK 1中的PID参数
    def set_velocity_parameters(self, kp, ki, kd, target_v_cm_s) -> int:
        """Update the tuning packet fields; identical revisions are applied only once."""
        return self.session.call("parameters", (
            TUNING_TASK_VELOCITY, VelocityParameters(kp, ki, kd, target_v_cm_s),
        ))

    ## 获取下位机任务执行结果（成功执行或者失败）
    def task_result(self, request_seq):
        telemetry = self.latest_telemetry
        if telemetry is None or telemetry.request_seq != request_seq:
            return None
        return bool(telemetry.status & STATUS_TASK_RESULT)

    ## 获取下位机调试参数应用结果（应用成功或者失败）
    def parameters_result(self, revision):
        telemetry = self.latest_telemetry
        if telemetry is None or telemetry.revision != revision:
            return None
        return bool(telemetry.status & STATUS_CONFIG_RESULT)

    ## 指定发送周期并开启发送
    def start_stream(self, period_seconds: float) -> None:
        if not math.isfinite(period_seconds) or period_seconds <= 0:
            raise ValueError("send period must be positive")
        self.session.call("stream", period_seconds)

    ## 停止发送
    def stop_stream(self) -> None:
        self.session.call("stream", None)

    ## 发送小球状态到通信线程
    def publish_ball_state(self, position: float, velocity: float, valid: bool,
                           *, measured_at: float | None = None) -> None:
        """Submit state; measured_at is the Pi image-read monotonic time."""
        self.session.publish_ball(position, velocity, valid, measured_at=measured_at)

    ## 更新视觉包发送状态并记录pi向stm32发送的数据
    def _record_sent_frame(self, frame, sent_at):
        packet = decode_pi_frame(frame)
        self.visual_state_sent = packet.tracking_valid
        callback = self.record_sent_frame
        if callback is None:
            return
        try:
            callback(packet, sent_at)
        except Exception as exc:
            self.record_sent_frame = None
            print(f"BALL_STATE 本地发包日志已停止：{exc}", file=sys.stderr, flush=True)

    ## 获取最新的电机角度，并调用角度记录器、控制采样记录器
    def _publish_telemetry(self, decoded, received_at):
        self.latest_telemetry = decoded
        telemetry = SimpleNamespace(actual_angle_deg=decoded.actual_angle_deg,
                                    received_monotonic=received_at)
        if self.record_actual_angle is not None:
            self.record_actual_angle(telemetry)             # 调用角度记录器（保存历史角度，供视觉标定）
        if decoded.sample is not None:
            if self.record_control_sample is not None:
                self.record_control_sample(decoded.sample)  # 调用控制采样记录器
