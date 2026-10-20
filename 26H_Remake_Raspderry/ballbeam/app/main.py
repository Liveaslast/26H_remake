#!/usr/bin/env python3
"""Assemble vision, MCU communication, task startup and optional outputs."""

import argparse
from contextlib import ExitStack
import os
import signal
import time

import cv2

from .arguments import parse_runtime_args
from ..vision.angles import AngleHistory, FrameAngleSource
from ..recording.capture import CaptureSession
from ..interfaces.presentation import (
    draw_missing_angle, publish_debug_state, report_capture_finished,
    start_debug_page, start_wifi_stream,
)
from .task_startup import (
    TaskRunner, confirm_mechanical_zero, initialize_task_startup, select_task,
    wait_for_first_angle,
)
from .tracking import build_tracking_components, run_tracking_loop
from ..communication.client import McuSerialClient
from ..errors import RuntimeIOError
from ..vision.calibration import DynamicCalibrationError
from ..vision.ball_state import BallStateBuilder, measurement_state


def run(args: argparse.Namespace) -> int:
    mode, task_id, task = select_task(args)
    if args.task_console:
        confirm_mechanical_zero()
    components = build_tracking_components(args, gravity_model_gain=args.gravity_model_gain)

    # 创建串口客户端、角度缓存器
    client = McuSerialClient(           # 创建串口客户端
        args.port,                                                      # 串口端口
        args.baudrate,                                                  # 波特率
        read_timeout_seconds=args.serial_read_timeout_ms / 1000.0,      # 读超时时间
        write_timeout_seconds=args.serial_write_timeout_ms / 1000.0,    # 写超时时间
    )
    angles = AngleHistory(history_samples=args.angle_history_samples)   # 创建角度缓存器（缓存电机角度，用于视觉标定）
    client.record_actual_angle = angles.record                          # 注册角度回调


    frame_angles = FrameAngleSource(                                    # 图像-电机角度匹配器
        angles, maximum_age_seconds=args.maximum_angle_age_ms / 1000.0,
        camera_latency_seconds=args.camera_latency_ms / 1000.0,
        calibration_range=components.calibration.angle_range_deg,
        clamp=args.clamp_calibration_angle,
    )
    ball_states = BallStateBuilder(state_source=measurement_state)      # 创建球状态获取器：明确采用测量状态，不额外滤波
    capture = CaptureSession(args, label=task.label)                    # 创建CSV采集管理器：对CSV数据采集进行管理
    tasks = TaskRunner(client, task_id=task_id,                         # 创建任务启动管理器
                       enabled=args.task_console)

    with ExitStack() as cleanup:
        # Stop communication before closing files used by its recording callbacks.
        cleanup.callback(capture.close)
        cleanup.callback(client.stop)

        ## 正式开始建立通信链路
        client.start()                                                  # 启动 McuCommunication 通信线程
        cleanup.callback(client.stop_stream)

        if not client.select_mode(mode):                                # 建立通信，请求模式
            raise RuntimeIOError(f"模式切换未确认：{client.last_error}")
        client.start_stream(1.0 / args.ball_state_send_rate_hz)         # 开启任务帧周期发送
        reading = wait_for_first_angle(client, angles, args.connect_timeout)    # 成功收到下位机的遥测帧
        print(f"STM32 telemetry ready: actual_angle={reading.angle_deg:+.3f}deg", flush=True)

        capture.open()                                                  # 打开CSV数据采集的管理器
        if capture.control is not None:
            client.record_control_sample = capture.control.publish      # 把记录函数交给客户端（回调）
            client.record_sent_frame = capture.sent.publish
            print(f"{capture.control.label} control CSV: {capture.control.path}", flush=True)
        initialize_task_startup(client, args, capture, task_id=task_id, task=task)      # 任务初始化

        page = None                                                                     # 调试界面
        if args.debug_page:
            page = start_debug_page(host=args.debug_host, port=args.debug_port,
                                    max_points=args.debug_max_points)
            cleanup.callback(page.stop)
        stream = None
        if args.wifi_stream:                                                            # 图传流
            stream = start_wifi_stream(args)
            cleanup.callback(stream.stop)

        ## 连接视觉和通信的关键接口：把视觉数据扔给客户端
        def handle_result(result):
            tasks.check_result()                                         # 检查任务请求结果
            if capture.finish_if_needed():                               # 检查采集串口是否结束
                client.record_control_sample = None
                client.record_sent_frame = None
                report_capture_finished(capture.control)
            state = ball_states.update(result)                           # 从视觉结果提取小球状态
            client.publish_ball_state(state.position_cm, state.velocity_cm_s, state.valid,      # 把小球状态更新到客户端
                                      measured_at=state.measured_at)
            capture.record_vision(result, state)                         # 记录视觉数据
            publish_debug_state(page, result, state)
            fresh = 0 <= time.monotonic() - state.measured_at <= 0.1
            if tasks.start_if_ready(state.valid and fresh):
                capture.start()

        return run_tracking_loop(                                         # 正式视觉运行循环
            components, args,
            angle_for_frame=frame_angles.for_frame,
            result_handler=handle_result,
            frame_handler=None if stream is None else stream.publish,
            fallback_overlay=draw_missing_angle,
            window_name="Dynamic Ball Tracking",
            hold_last_display_on_missing=True,
        )


def main() -> int:
    args = parse_runtime_args()
    if args.task_console:
        def exit_upper_only(_signum, _frame) -> None:
            os.write(2, "\n收到 Ctrl+C：树莓派程序立即退出；下位机请手动复位。\n".encode("utf-8"))
            os._exit(130)

        signal.signal(signal.SIGINT, exit_upper_only)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Tracking stopped by user.", flush=True)
        return 130
    except (DynamicCalibrationError, RuntimeIOError, ValueError, cv2.error) as exc:
        print(f"Tracking failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
