"""Serial and debug-page sinks for the formal balance-control loop."""

from __future__ import annotations

import argparse
from collections import deque
import csv
import math
from pathlib import Path
import threading
import time
from typing import Any

from ..control.balance import (
    BalanceController,
    BalanceControllerConfig,
)
from ..vision.tracker import DynamicTrackingResult
from ..hardware.runtime import RuntimeIOError


def start_debug_page(
    *,
    host: str,
    port: int,
    max_points: int,
) -> Any:
    """Lazily start DebugPage so normal operation does not require Flask."""

    try:
        from ..interfaces.debug_page import DebugPage
    except ImportError as exc:
        raise RuntimeIOError(
            "缺少debug_page依赖；请安装best/debug_page/requirements.txt"
        ) from exc
    page = DebugPage(
        host=host,
        port=port,
        max_points=max_points,
        title="钢球平衡控制调试",
    )
    page.start()
    return page


def add_balance_arguments(
    parser: argparse.ArgumentParser,
    *,
    allow_actuator: bool,
) -> None:
    """Add shared target-angle and DebugPage options."""

    if allow_actuator:
        parser.add_argument(
            "--enable-balance-control",
            action="store_true",
            help="允许MSPM0执行目标角度；默认只发送数据但不使能执行器",
        )
        parser.add_argument(
            "--clear-estop",
            action="store_true",
            help=(
                "启动后显式请求清除MSPM0急停；"
                "仅与--enable-balance-control同用"
            ),
        )
    parser.add_argument("--target-position-cm", type=float)
    parser.add_argument(
        "--control-kp",
        type=float,
        help="位置比例增益，单位deg/cm",
    )
    parser.add_argument(
        "--control-kd",
        type=float,
        help="速度反馈增益，单位deg/(cm/s)",
    )
    parser.add_argument(
        "--control-ki",
        type=float,
        help="位置积分增益，单位deg/(cm*s)",
    )
    parser.add_argument("--maximum-target-angle-deg", type=float)
    parser.add_argument(
        "--maximum-target-slew-deg-s",
        type=float,
    )
    parser.add_argument("--invalid-return-deg-s", type=float)
    parser.add_argument("--integral-limit-cm-s", type=float)
    parser.add_argument("--maximum-control-step-ms", type=float)
    parser.add_argument(
        "--debug-page",
        action="store_true",
        help="发布钢球位置、速度和目标/实际角度到DebugPage",
    )
    parser.add_argument(
        "--no-debug-page",
        dest="debug_page",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--debug-host")
    parser.add_argument("--debug-port", type=int)
    parser.add_argument("--debug-max-points", type=int)


def add_ball_state_arguments(parser: argparse.ArgumentParser) -> None:
    """Add DebugPage options for the formal MCU-control runtime."""

    parser.add_argument(
        "--ball-state-send-rate-hz",
        type=float,
        help="fixed MCU BALL_STATE transmit rate; latest vision state wins",
    )
    parser.add_argument(
        "--ball-position-lowpass-tau-ms",
        type=float,
        help="MCU前发送位置一阶低通时间常数；0表示关闭",
    )
    parser.add_argument(
        "--ball-position-median-window",
        type=int,
        help="MCU前发送位置中值滤波窗口；1表示关闭",
    )
    parser.add_argument(
        "--ball-position-deadband-cm",
        type=float,
        help="MCU前发送位置小变化忽略阈值；0表示关闭",
    )
    parser.add_argument(
        "--ball-position-slew-limit-cm-s",
        type=float,
        help="MCU前发送位置最大变化率；0表示关闭",
    )
    parser.add_argument(
        "--ball-position-jump-threshold-cm",
        type=float,
        help="位置跳变确认阈值；0表示关闭",
    )
    parser.add_argument(
        "--ball-position-jump-confirm-ms",
        type=float,
        help="位置跳变接受前必须持续的时间；0表示关闭",
    )
    parser.add_argument(
        "--ball-ignore-zero-position-cm",
        type=float,
        help="疑似假0位置阈值；0表示关闭",
    )
    parser.add_argument(
        "--ball-velocity-lowpass-tau-ms",
        type=float,
        help="MCU前发送速度一阶低通时间常数；0表示关闭",
    )
    parser.add_argument(
        "--ball-velocity-deadband-cm-s",
        type=float,
        help="MCU前发送速度死区；绝对值低于该值直接置0",
    )
    parser.add_argument(
        "--vision-probe-csv",
        type=Path,
        help="记录raw/filtered视觉数据到CSV，便于排查视觉抖动",
    )
    parser.add_argument(
        "--vision-probe-print",
        action="store_true",
        help="在终端打印raw/filtered视觉数据；默认只写CSV/发串口",
    )

    parser.add_argument(
        "--debug-page",
        action="store_true",
        help="发布钢球位置、速度、有效性和摆杆实际角度到DebugPage",
    )
    parser.add_argument(
        "--no-debug-page",
        dest="debug_page",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--debug-host")
    parser.add_argument("--debug-port", type=int)
    parser.add_argument("--debug-max-points", type=int)


def validate_ball_state_arguments(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
    if (
        not math.isfinite(args.ball_state_send_rate_hz)
        or not 50.0 <= args.ball_state_send_rate_hz <= 100.0
    ):
        parser.error("--ball-state-send-rate-hz must be within [50,100]")
    if not 0 <= args.debug_port <= 65535:
        parser.error("--debug-port必须在0到65535之间")
    if args.debug_max_points < 2:
        parser.error("--debug-max-points必须至少为2")
    if args.ball_position_median_window < 1:
        parser.error("--ball-position-median-window必须至少为1")
    filter_values = (
        args.ball_position_lowpass_tau_ms,
        args.ball_position_deadband_cm,
        args.ball_position_slew_limit_cm_s,
        args.ball_position_jump_threshold_cm,
        args.ball_position_jump_confirm_ms,
        args.ball_ignore_zero_position_cm,
        args.ball_velocity_lowpass_tau_ms,
        args.ball_velocity_deadband_cm_s,
    )
    if not all(math.isfinite(value) and value >= 0.0 for value in filter_values):
        parser.error("BALL_STATE发送前滤波与死区参数必须是有限非负数")


def validate_balance_arguments(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    allow_actuator: bool,
) -> None:
    control_values = (
        args.target_position_cm,
        args.control_kp,
        args.control_kd,
        args.control_ki,
        args.maximum_target_angle_deg,
        args.maximum_target_slew_deg_s,
        args.invalid_return_deg_s,
        args.integral_limit_cm_s,
        args.maximum_control_step_ms,
    )
    if not all(math.isfinite(value) for value in control_values):
        parser.error("控制器参数必须是有限数值")
    if min(control_values[4:]) <= 0:
        parser.error("控制器限幅、变化率和积分限幅必须为正数")
    if allow_actuator:
        if args.enable_balance_control and not args.clear_estop:
            parser.error(
                "--enable-balance-control必须同时显式指定--clear-estop"
            )
        if args.clear_estop and not args.enable_balance_control:
            parser.error("--clear-estop只能与--enable-balance-control同用")
    if not 0 <= args.debug_port <= 65535:
        parser.error("--debug-port必须在0到65535之间")
    if args.debug_max_points < 2:
        parser.error("--debug-max-points必须至少为2")


def build_balance_controller(
    args: argparse.Namespace,
    *,
    actuator_enabled: bool,
) -> BalanceController:
    return BalanceController(
        BalanceControllerConfig(
            target_position_cm=args.target_position_cm,
            kp_deg_per_cm=args.control_kp,
            kd_deg_per_cm_s=args.control_kd,
            ki_deg_per_cm_s=args.control_ki,
            maximum_angle_deg=args.maximum_target_angle_deg,
            maximum_slew_deg_s=args.maximum_target_slew_deg_s,
            invalid_return_deg_s=args.invalid_return_deg_s,
            integral_limit_cm_s=args.integral_limit_cm_s,
            maximum_step_seconds=args.maximum_control_step_ms / 1000.0,
        ),
        actuator_enabled=actuator_enabled,
    )


class BalanceRuntime:
    """Send every control sample and optionally mirror it to DebugPage."""

    def __init__(
        self,
        *,
        controller: BalanceController,
        client: Any | None = None,
        debug_page: Any | None = None,
    ) -> None:
        self.controller = controller
        self.client = client
        self.debug_page = debug_page
        self.send_failures = 0

    def handle_result(self, result: DynamicTrackingResult) -> None:
        command = self.controller.update(result)
        if self.client is not None:
            if not self.client.send_balance_control(
                command.ball_position_cm,
                command.ball_velocity_cm_s,
                command.target_angle_deg,
                enable=command.enable,
                tracking_valid=command.tracking_valid,
            ):
                self.send_failures += 1

        page = self.debug_page
        if page is None:
            return
        values = {
            "ball_position_cm": command.ball_position_cm,
            "ball_velocity_cm_s": command.ball_velocity_cm_s,
            "target_angle_deg": command.target_angle_deg,
            "tracking_valid": float(command.tracking_valid),
            "control_enabled": float(command.enable),
        }
        if result.actual_angle_deg is not None:
            values["actual_angle_deg"] = result.actual_angle_deg
        page.publish(values)


class VisionProbeLogger:
    """Record raw tracker output next to the filtered MCU command."""

    _HEADER = (
        "t",
        "frame_seq",
        "result_ready_t",
        "capture_to_log_ms",
        "inference_ms",
        "refinement_ms",
        "processing_ms",
        "raw_x_cm",
        "sent_x_cm",
        "raw_vx_cm_s",
        "sent_vx_cm_s",
        "measurement_valid",
        "tracking_valid",
        "sent_valid",
        "confidence",
        "source",
        "reason",
        "actual_angle_deg",
        "center_x_px",
        "center_y_px",
        "radius_px",
        "measurement_x_cm",
        "kalman_x_cm",
        "kalman_vx_cm_s",
    )

    def __init__(
        self,
        *,
        path: Path | None = None,
        print_rows: bool = False,
    ) -> None:
        self.path = path
        self.print_rows = print_rows
        self._file = None
        self._writer: csv.writer | None = None
        self._frame_seq = 0
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            self._writer.writerow(self._HEADER)
            self._file.flush()

    @staticmethod
    def _number(value: float | None) -> str:
        if value is None or not math.isfinite(value):
            return ""
        return f"{value:.4f}"

    @staticmethod
    def _source_name(source: Any) -> str:
        return str(getattr(source, "value", source))

    def publish(
        self,
        *,
        result: DynamicTrackingResult,
        sent_position_cm: float,
        sent_velocity_cm_s: float,
        sent_valid: bool,
    ) -> None:
        result_ready_t = time.perf_counter()
        self._frame_seq += 1
        center_x = None
        center_y = None
        if result.center_px is not None:
            center_x, center_y = result.center_px
        row = [
            f"{float(result.timestamp):.6f}",
            self._frame_seq,
            f"{result_ready_t:.6f}",
            f"{(result_ready_t - float(result.timestamp)) * 1000.0:.4f}",
            self._number(result.inference_ms),
            self._number(result.refinement_ms),
            self._number(result.processing_ms),
            self._number(result.position_cm),
            self._number(sent_position_cm),
            self._number(result.velocity_cm_s),
            self._number(sent_velocity_cm_s),
            int(result.measurement_valid),
            int(result.tracking_valid),
            int(sent_valid),
            self._number(result.confidence),
            self._source_name(result.source),
            result.reason,
            self._number(result.actual_angle_deg),
            self._number(center_x),
            self._number(center_y),
            self._number(result.radius_px),
            self._number(getattr(result, "measurement_position_cm", None)),
            self._number(result.position_cm),
            self._number(result.velocity_cm_s),
        ]
        writer = self._writer
        if writer is not None:
            writer.writerow(row)
            if self._file is not None:
                self._file.flush()
        if self.print_rows:
            print(
                "vision_probe "
                f"frame={row[1]} infer={row[4] or 'nan'}ms "
                f"total={row[6] or 'nan'}ms "
                f"raw_x={row[7] or 'nan'} sent_x={row[8]} "
                f"raw_vx={row[9] or 'nan'} sent_vx={row[10]} "
                f"meas={row[11]} track={row[12]} sent={row[13]} "
                f"conf={row[14] or 'nan'} source={row[15]} reason={row[16]}",
                flush=True,
            )

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None


class BallStateRuntime:
    """Publish only the newest vision state from a fixed-rate TX thread."""

    def __init__(
        self,
        *,
        client: Any,
        debug_page: Any | None = None,
        send_period_seconds: float = 0.01,
        position_lowpass_tau_seconds: float = 0.0,
        position_median_window: int = 1,
        position_deadband_cm: float = 0.0,
        position_slew_limit_cm_s: float = 0.0,
        position_jump_threshold_cm: float = 0.0,
        position_jump_confirm_seconds: float = 0.0,
        ignore_zero_position_cm: float = 0.0,
        velocity_lowpass_tau_seconds: float = 0.0,
        velocity_deadband_cm_s: float = 0.0,
        vision_probe: VisionProbeLogger | None = None,
    ) -> None:
        if not math.isfinite(send_period_seconds) or send_period_seconds <= 0:
            raise ValueError("send_period_seconds must be finite and positive")
        filter_values = (
            position_lowpass_tau_seconds,
            position_deadband_cm,
            position_slew_limit_cm_s,
            position_jump_threshold_cm,
            position_jump_confirm_seconds,
            ignore_zero_position_cm,
            velocity_lowpass_tau_seconds,
            velocity_deadband_cm_s,
        )
        if not all(math.isfinite(value) and value >= 0.0 for value in filter_values):
            raise ValueError("filter parameters must be finite and non-negative")
        if position_median_window < 1:
            raise ValueError("position_median_window must be at least 1")
        self.client = client
        self.debug_page = debug_page
        self.send_period_seconds = float(send_period_seconds)
        self.position_lowpass_tau_seconds = float(position_lowpass_tau_seconds)
        self.position_median_window = int(position_median_window)
        self.position_deadband_cm = float(position_deadband_cm)
        self.position_slew_limit_cm_s = float(position_slew_limit_cm_s)
        self.position_jump_threshold_cm = float(position_jump_threshold_cm)
        self.position_jump_confirm_seconds = float(position_jump_confirm_seconds)
        self.ignore_zero_position_cm = float(ignore_zero_position_cm)
        self.velocity_lowpass_tau_seconds = float(velocity_lowpass_tau_seconds)
        self.velocity_deadband_cm_s = float(velocity_deadband_cm_s)
        self.vision_probe = vision_probe
        self.send_failures = 0
        self._last_position_cm = 0.0
        self._last_velocity_cm_s = 0.0
        self._last_measurement_time: float | None = None
        self._has_measurement = False
        self._position_samples: deque[float] = deque(
            maxlen=self.position_median_window
        )
        self._pending_position_cm: float | None = None
        self._pending_position_since: float | None = None
        self._latest_state: tuple[float, float, bool] | None = None
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._sender_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the fixed-rate sender; repeated calls are harmless."""

        with self._condition:
            thread = self._sender_thread
            if thread is not None and thread.is_alive():
                return
            self._stop_event.clear()
            self._sender_thread = threading.Thread(
                target=self._sender_loop,
                name="BallStateLatestSender",
                daemon=True,
            )
            self._sender_thread.start()

    def stop(self) -> None:
        """Stop the sender before the underlying serial client is closed."""

        with self._condition:
            self._stop_event.set()
            self._condition.notify_all()
            thread = self._sender_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.send_period_seconds * 3.0))
        with self._condition:
            self._sender_thread = None

    def _sender_loop(self) -> None:
        with self._condition:
            while self._latest_state is None and not self._stop_event.is_set():
                self._condition.wait()
        next_send = time.perf_counter()
        while not self._stop_event.is_set():
            now = time.perf_counter()
            if now < next_send and self._stop_event.wait(next_send - now):
                break
            with self._condition:
                state = self._latest_state
            if state is not None:
                position, velocity, tracking_valid = state
                try:
                    sent = self.client.send_ball_state(
                        position,
                        velocity,
                        tracking_valid=tracking_valid,
                    )
                except Exception:
                    sent = False
                if not sent:
                    self.send_failures += 1
            next_send += self.send_period_seconds
            now = time.perf_counter()
            if next_send <= now:
                next_send = now + self.send_period_seconds

    @staticmethod
    def _lowpass(previous: float, value: float, dt: float, tau: float) -> float:
        if tau <= 0.0 or dt <= 0.0:
            return value
        alpha = dt / (tau + dt)
        return previous + alpha * (value - previous)

    @staticmethod
    def _slew_limit(previous: float, value: float, dt: float, rate: float) -> float:
        if rate <= 0.0 or dt <= 0.0:
            return value
        maximum_delta = rate * dt
        delta = value - previous
        if delta > maximum_delta:
            return previous + maximum_delta
        if delta < -maximum_delta:
            return previous - maximum_delta
        return value

    @staticmethod
    def _median(values) -> float:
        ordered = sorted(values)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[midpoint]
        return 0.5 * (ordered[midpoint - 1] + ordered[midpoint])

    def _confirm_position_jump(self, value: float, timestamp: float) -> float:
        if (
            self.position_jump_threshold_cm <= 0.0
            or self.position_jump_confirm_seconds <= 0.0
            or not self._has_measurement
            or abs(value - self._last_position_cm) < self.position_jump_threshold_cm
        ):
            self._pending_position_cm = None
            self._pending_position_since = None
            return value

        pending = self._pending_position_cm
        if (
            pending is None
            or abs(value - pending) >= self.position_jump_threshold_cm
        ):
            self._pending_position_cm = value
            self._pending_position_since = timestamp
            return self._last_position_cm

        since = self._pending_position_since
        if since is None or (timestamp - since) < self.position_jump_confirm_seconds:
            return self._last_position_cm

        self._pending_position_cm = None
        self._pending_position_since = None
        return value

    def _reject_suspicious_zero(self, value: float) -> float:
        if (
            self.ignore_zero_position_cm <= 0.0
            or not self._has_measurement
            or abs(value) > self.ignore_zero_position_cm
            or abs(self._last_position_cm) <= self.position_jump_threshold_cm
        ):
            return value
        return self._last_position_cm

    def handle_result(self, result: DynamicTrackingResult) -> None:
        measured_position = getattr(result, "measurement_position_cm", None)
        position = (
            measured_position
            if measured_position is not None and result.measurement_valid
            else result.position_cm
        )
        velocity = result.velocity_cm_s
        current_measurement = (
            result.measurement_valid
            and result.tracking_valid
            and position is not None
            and velocity is not None
            and math.isfinite(position)
            and math.isfinite(velocity)
        )
        if current_measurement:
            raw_position = float(position)
            raw_velocity = float(velocity)
            raw_position = self._reject_suspicious_zero(raw_position)
            self._position_samples.append(raw_position)
            stable_position = self._median(self._position_samples)
            stable_position = self._confirm_position_jump(
                stable_position,
                float(result.timestamp),
            )
            last_time = self._last_measurement_time
            dt = (
                0.0
                if last_time is None
                else max(0.0, float(result.timestamp) - last_time)
            )
            if not self._has_measurement:
                next_position = stable_position
                next_velocity = raw_velocity
            else:
                if (
                    self.position_deadband_cm > 0.0
                    and abs(stable_position - self._last_position_cm)
                    < self.position_deadband_cm
                ):
                    next_position = self._last_position_cm
                else:
                    next_position = self._lowpass(
                        self._last_position_cm,
                        stable_position,
                        dt,
                        self.position_lowpass_tau_seconds,
                    )
                next_position = self._slew_limit(
                    self._last_position_cm,
                    next_position,
                    dt,
                    self.position_slew_limit_cm_s,
                )
                next_velocity = self._lowpass(
                    self._last_velocity_cm_s,
                    raw_velocity,
                    dt,
                    self.velocity_lowpass_tau_seconds,
                )
            if (
                self.velocity_deadband_cm_s > 0.0
                and abs(next_velocity) < self.velocity_deadband_cm_s
            ):
                next_velocity = 0.0
        else:
            next_position = self._last_position_cm
            next_velocity = self._last_velocity_cm_s

        tracking_valid = bool(current_measurement)
        with self._condition:
            if current_measurement:
                self._last_position_cm = next_position
                self._last_velocity_cm_s = next_velocity
                self._last_measurement_time = float(result.timestamp)
                self._has_measurement = True
            self._latest_state = (
                self._last_position_cm,
                self._last_velocity_cm_s,
                tracking_valid,
            )
            self._condition.notify_all()

        probe = self.vision_probe
        if probe is not None:
            probe.publish(
                result=result,
                sent_position_cm=self._last_position_cm,
                sent_velocity_cm_s=self._last_velocity_cm_s,
                sent_valid=tracking_valid,
            )

        page = self.debug_page
        if page is None:
            return
        values = {
            "ball_position_cm": self._last_position_cm,
            "ball_velocity_cm_s": self._last_velocity_cm_s,
            "tracking_valid": float(tracking_valid),
        }
        if (
            result.actual_angle_deg is not None
            and math.isfinite(result.actual_angle_deg)
        ):
            values["actual_angle_deg"] = float(result.actual_angle_deg)
        page.publish(values)
