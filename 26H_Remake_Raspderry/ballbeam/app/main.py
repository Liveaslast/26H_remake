#!/usr/bin/env python3
"""固定车身相机下的摆杆动态展开和钢球实时跟踪主程序。"""

from __future__ import annotations

import argparse
import math

import cv2

from .tracking_loop import FrameAngle, run_tracking_loop
from .balance_runtime import (
    BallStateRuntime,
    VisionProbeLogger,
    add_ball_state_arguments,
    start_debug_page,
    validate_ball_state_arguments,
)
from .tracking_setup import (
    add_common_tracking_arguments,
    build_tracking_components,
    validate_common_tracking_args,
)
from ..config import (
    add_config_argument,
    parse_args_with_config,
)
from ..vision.calibration import DynamicCalibrationError
from ..vision.tracker import DynamicTrackingResult
from ..hardware.runtime import (
    RuntimeIOError,
    TelemetryAngleSource,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "actual_angle_deg 动态透视展开 + Hailo/NCNN 检测；"
            "正式坐标取 YOLO bbox 中心。"
        )
    )
    add_config_argument(parser)
    add_common_tracking_arguments(parser)
    parser.add_argument("--port")
    parser.add_argument("--baudrate", type=int)
    parser.add_argument("--connect-timeout", type=float)
    parser.add_argument(
        "--maximum-angle-age-ms",
        type=float,
        help="相机帧对应角度遥测的最大时间差（默认：100ms）",
    )
    parser.add_argument(
        "--camera-latency-ms",
        type=float,
        help="从曝光中心到 read() 返回的估计延迟（默认：16.7ms）",
    )
    parser.add_argument(
        "--clamp-calibration-angle",
        action="store_true",
        default=True,
        help="实际角度超出动态标定范围时，夹到标定边界后继续展开",
    )
    parser.add_argument(
        "--no-clamp-calibration-angle",
        dest="clamp_calibration_angle",
        action="store_false",
        help="实际角度超出动态标定范围时直接判为视觉无效",
    )
    parser.add_argument(
        "--gravity-model-gain",
        type=float,
        help=(
            "角度加速度模型增益，默认0关闭；确认坐标符号后可从±0.714开始整定"
        ),
    )
    parser.add_argument("--telemetry-request-period-ms", type=float)
    parser.add_argument("--telemetry-link-timeout-ms", type=float)
    parser.add_argument("--serial-read-timeout-ms", type=float)
    parser.add_argument("--serial-write-timeout-ms", type=float)
    parser.add_argument("--heartbeat-period-ms", type=float)
    parser.add_argument("--reconnect-period-ms", type=float)
    parser.add_argument("--angle-history-samples", type=int)
    parser.add_argument(
        "--wifi-stream",
        action="store_true",
        help="在当前跟踪进程内启用WIFI_test MJPEG图传，不重复打开相机",
    )
    parser.add_argument("--wifi-host", default="0.0.0.0")
    parser.add_argument("--wifi-port", type=int, default=8080)
    parser.add_argument("--wifi-stream-width", type=int, default=640)
    parser.add_argument("--wifi-stream-height", type=int, default=360)
    parser.add_argument("--wifi-stream-fps", type=float, default=20.0)
    parser.add_argument("--wifi-jpeg-quality", type=int, default=75)
    add_ball_state_arguments(parser)
    return parser


def validate_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
    validate_common_tracking_args(args, parser)
    if not args.port:
        parser.error("--port不能为空")
    if args.baudrate <= 0:
        parser.error("--baudrate必须为正数")
    if not math.isfinite(args.connect_timeout) or args.connect_timeout <= 0:
        parser.error("--connect-timeout 必须为正数")
    if not math.isfinite(args.maximum_angle_age_ms) or args.maximum_angle_age_ms <= 0:
        parser.error("--maximum-angle-age-ms 必须为正数")
    if not math.isfinite(args.camera_latency_ms) or args.camera_latency_ms < 0:
        parser.error("--camera-latency-ms 不能为负数")
    if not math.isfinite(args.gravity_model_gain):
        parser.error("--gravity-model-gain 必须是有限数值")
    serial_timings = (
        args.telemetry_request_period_ms,
        args.telemetry_link_timeout_ms,
        args.serial_read_timeout_ms,
        args.serial_write_timeout_ms,
        args.heartbeat_period_ms,
        args.reconnect_period_ms,
    )
    if min(serial_timings) <= 0 or not all(
        math.isfinite(value) for value in serial_timings
    ):
        parser.error("串口与遥测时序参数必须是有限正数")
    if args.angle_history_samples < 2:
        parser.error("--angle-history-samples必须至少为2")
    if not args.wifi_host:
        parser.error("--wifi-host不能为空")
    if not 0 <= args.wifi_port <= 65535:
        parser.error("--wifi-port必须在0到65535之间")
    if args.wifi_stream_width < 2 or args.wifi_stream_height < 2:
        parser.error("WiFi图传宽高必须至少为2像素")
    if not math.isfinite(args.wifi_stream_fps) or args.wifi_stream_fps <= 0:
        parser.error("--wifi-stream-fps必须是有限正数")
    if not 1 <= args.wifi_jpeg_quality <= 100:
        parser.error("--wifi-jpeg-quality必须在1到100之间")
    validate_ball_state_arguments(args, parser)


def draw_missing_angle(
    frame,
    result: DynamicTrackingResult,
    *,
    fps: float | None = None,
):
    canvas = frame.copy()
    panel_height = min(72, canvas.shape[0])
    cv2.rectangle(
        canvas,
        (0, 0),
        (canvas.shape[1] - 1, panel_height - 1),
        (0, 0, 0),
        -1,
    )
    warning = (
        "ANGLE TELEMETRY STALE"
        if result.reason == "angle-telemetry-stale"
        else "TRACKING DISPLAY FROZEN"
    )
    cv2.putText(
        canvas,
        warning,
        (12, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        (
            f"reason={result.reason} fps="
            f"{'warming' if fps is None else f'{fps:.1f}'}"
        ),
        (12, 58),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.60,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return canvas


def require_ball_state_support(client) -> None:
    """Fail before tracking if the MCU does not acknowledge BALL_STATE."""

    if not client.send_ball_state(
        0.0,
        0.0,
        tracking_valid=False,
        wait_ack=True,
    ):
        raise RuntimeIOError(
            "MSPM0未确认BALL_STATE(0x07)；请先刷写支持新视觉状态协议的固件"
        )


def start_wifi_stream(args: argparse.Namespace):
    """Start WIFI_test in-process so tracking remains the only camera owner."""

    try:
        from ..interfaces.wifi_stream.mjpeg_stream import (
            MJPEGStreamConfig,
            MJPEGStreamServer,
        )
    except ImportError as exc:
        raise RuntimeIOError(
            "无法导入 ballbeam.interfaces.wifi_stream 及其依赖"
        ) from exc

    try:
        stream = MJPEGStreamServer(
            MJPEGStreamConfig(
                host=args.wifi_host,
                port=args.wifi_port,
                width=args.wifi_stream_width,
                height=args.wifi_stream_height,
                fps=args.wifi_stream_fps,
                jpeg_quality=args.wifi_jpeg_quality,
            )
        )
        stream.start()
    except (RuntimeError, ValueError, OSError) as exc:
        raise RuntimeIOError(f"WiFi MJPEG图传启动失败：{exc}") from exc

    print(
        "WiFi MJPEG ready: "
        f"http://<设备IP>:{stream.bound_port}/ "
        f"(VLC: http://<设备IP>:{stream.bound_port}/stream.mjpg)",
        flush=True,
    )
    return stream


def run(args: argparse.Namespace) -> int:
    components = build_tracking_components(
        args,
        gravity_model_gain=args.gravity_model_gain,
    )
    angle_source = TelemetryAngleSource(
        args.port,
        args.baudrate,
        request_period_seconds=args.telemetry_request_period_ms / 1000.0,
        link_timeout_seconds=args.telemetry_link_timeout_ms / 1000.0,
        read_timeout_seconds=args.serial_read_timeout_ms / 1000.0,
        write_timeout_seconds=args.serial_write_timeout_ms / 1000.0,
        heartbeat_period_seconds=args.heartbeat_period_ms / 1000.0,
        reconnect_period_seconds=args.reconnect_period_ms / 1000.0,
        history_samples=args.angle_history_samples,
        estop_on_stop=False,
    )
    angle_maximum_age = args.maximum_angle_age_ms / 1000.0
    camera_latency = args.camera_latency_ms / 1000.0
    calibration_angle_min, calibration_angle_max = (
        components.calibration.angle_range_deg
    )
    debug_page = None
    wifi_stream = None
    balance_runtime = None
    vision_probe = None

    try:
        angle_source.start()
        reading = angle_source.wait_for_first_reading(args.connect_timeout)
        print(
            f"MSPM0 telemetry ready: actual_angle="
            f"{reading.angle_deg:+.3f}deg",
            flush=True,
        )
        require_ball_state_support(angle_source.client)
        print(
            "Ball position/velocity streaming enabled; control runs on MCU.",
            flush=True,
        )
        if args.debug_page:
            debug_page = start_debug_page(
                host=args.debug_host,
                port=args.debug_port,
                max_points=args.debug_max_points,
            )
        if args.wifi_stream:
            wifi_stream = start_wifi_stream(args)
        if args.vision_probe_csv is not None or args.vision_probe_print:
            vision_probe = VisionProbeLogger(
                path=args.vision_probe_csv,
                print_rows=args.vision_probe_print,
            )
            if args.vision_probe_csv is not None:
                print(f"Vision probe CSV: {args.vision_probe_csv}", flush=True)
        balance_runtime = BallStateRuntime(
            client=angle_source.client,
            debug_page=debug_page,
            send_period_seconds=1.0 / args.ball_state_send_rate_hz,
            position_lowpass_tau_seconds=(
                args.ball_position_lowpass_tau_ms / 1000.0
            ),
            position_median_window=args.ball_position_median_window,
            position_deadband_cm=args.ball_position_deadband_cm,
            position_slew_limit_cm_s=args.ball_position_slew_limit_cm_s,
            position_jump_threshold_cm=args.ball_position_jump_threshold_cm,
            position_jump_confirm_seconds=(
                args.ball_position_jump_confirm_ms / 1000.0
            ),
            ignore_zero_position_cm=args.ball_ignore_zero_position_cm,
            velocity_lowpass_tau_seconds=(
                args.ball_velocity_lowpass_tau_ms / 1000.0
            ),
            velocity_deadband_cm_s=args.ball_velocity_deadband_cm_s,
            vision_probe=vision_probe,
        )
        balance_runtime.start()

        def angle_for_frame(captured_monotonic: float) -> FrameAngle:
            angle_source.poll(captured_monotonic)
            angle_timestamp = captured_monotonic - camera_latency
            angle = angle_source.angle_at(
                angle_timestamp,
                maximum_age_seconds=angle_maximum_age,
            )
            if angle is None:
                return FrameAngle(
                    angle_deg=None,
                    invalid_reason="angle-telemetry-stale",
                )
            actual_angle = angle.angle_deg
            if args.clamp_calibration_angle:
                clamped_angle = min(
                    max(actual_angle, calibration_angle_min),
                    calibration_angle_max,
                )
                if clamped_angle != actual_angle:
                    return FrameAngle(
                        angle_deg=clamped_angle,
                        report_prefix=(
                            f"angle-clamped raw={actual_angle:+.3f}deg "
                            f"used={clamped_angle:+.3f}deg "
                        ),
                    )
            return FrameAngle(angle_deg=actual_angle)

        return run_tracking_loop(
            components,
            args,
            angle_for_frame=angle_for_frame,
            before_capture=angle_source.poll,
            window_name="Dynamic Ball Tracking",
            fallback_overlay=lambda frame, result, fps: draw_missing_angle(
                frame,
                result,
                fps=fps,
            ),
            result_handler=balance_runtime.handle_result,
            frame_handler=(
                None if wifi_stream is None else wifi_stream.publish
            ),
            hold_last_display_on_missing=True,
        )
    finally:
        if balance_runtime is not None:
            balance_runtime.stop()
        if wifi_stream is not None:
            wifi_stream.stop()
        if debug_page is not None:
            debug_page.stop()
        if vision_probe is not None:
            vision_probe.close()
        angle_source.stop()


def main() -> int:
    parser = build_parser()
    args = parse_args_with_config(
        parser,
        sections=(
            "vision_geometry",
            "tracking",
            "detector",
            "tracker",
            "debug",
            "formal_tracking",
        ),
    )
    validate_args(args, parser)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Tracking stopped by user.", flush=True)
        return 130
    except (
        DynamicCalibrationError,
        RuntimeIOError,
        ValueError,
        cv2.error,
    ) as exc:
        print(f"Tracking failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
