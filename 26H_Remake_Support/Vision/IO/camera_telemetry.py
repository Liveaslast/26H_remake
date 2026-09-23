"""USB相机和MSPM0实际摆杆角度的运行时接口。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
from pathlib import Path
import subprocess
import struct
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
import serial

from ..Config.paths import WORKSPACE_ROOT


class RuntimeIOError(RuntimeError):
    """相机或角度遥测无法提供有效数据。"""


@dataclass(slots=True)
class FrameRateMeter:
    """Measure actual loop FPS over a short sliding time window."""

    window_seconds: float = 1.0
    maximum_samples: int = 512
    _timestamps: deque[float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.window_seconds = float(self.window_seconds)
        self.maximum_samples = int(self.maximum_samples)
        if not math.isfinite(self.window_seconds) or self.window_seconds <= 0:
            raise ValueError("FPS统计窗口必须为正数")
        if self.maximum_samples < 2:
            raise ValueError("FPS统计最大样本数必须至少为2")
        self._timestamps = deque(maxlen=self.maximum_samples)

    def update(self, timestamp: float | None = None) -> float | None:
        """Add a completed frame and return smoothed FPS when available."""

        current = (
            time.perf_counter()
            if timestamp is None
            else float(timestamp)
        )
        if not math.isfinite(current):
            raise ValueError("FPS时间戳必须是有限数值")
        if self._timestamps and current <= self._timestamps[-1]:
            self._timestamps.clear()
        self._timestamps.append(current)
        cutoff = current - self.window_seconds
        while len(self._timestamps) > 1 and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) < 2:
            return None
        elapsed = self._timestamps[-1] - self._timestamps[0]
        if elapsed <= 1e-9:
            return None
        return (len(self._timestamps) - 1) / elapsed


@dataclass(frozen=True, slots=True)
class CameraMode:
    device: str = "/dev/video0"
    width: int = 1280
    height: int = 720
    fps: float = 60.0
    fourcc: str = "MJPG"
    buffer_size: int = 2
    disable_dynamic_framerate: bool = True
    exposure_time_absolute: int | None = None
    read_timeout_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.device:
            raise ValueError("相机设备不能为空")
        if self.width < 2 or self.height < 2:
            raise ValueError("相机分辨率无效")
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("相机帧率必须为正数")
        if len(self.fourcc) != 4:
            raise ValueError("fourcc 必须正好包含四个字符")
        if self.buffer_size < 1:
            raise ValueError("相机缓冲帧数必须至少为1")
        if (
            self.exposure_time_absolute is not None
            and self.exposure_time_absolute < 1
        ):
            raise ValueError("exposure_time_absolute must be at least 1")
        if (
            not math.isfinite(self.read_timeout_seconds)
            or self.read_timeout_seconds <= 0
        ):
            raise ValueError("相机读帧超时必须为正数")


class FixedUSBCamera:
    """严格打开指定 V4L2/MJPG 模式，避免标定后分辨率悄然变化。"""

    def __init__(self, mode: CameraMode) -> None:
        self.mode = mode
        self._capture: cv2.VideoCapture | None = None
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._latest_frame: np.ndarray | None = None
        self._latest_timestamp: float | None = None
        self._latest_sequence = 0
        self._delivered_sequence = 0
        self._reader_error: RuntimeIOError | None = None

    @staticmethod
    def _capture_device(device: str) -> str | int:
        if device.isdecimal():
            return int(device)
        return device

    def _configure_v4l2_frame_timing(self) -> None:
        """Lock UVC exposure controls needed by the calibrated vision path.

        OpenCV has no property for ``exposure_dynamic_framerate``. Configure
        V4L2 controls once, after selecting the capture format. A fixed short
        exposure prevents a rolling steel ball from becoming a blurred streak.
        Unsupported cameras remain usable because these controls do not change
        image geometry.
        """

        if (
            not sys.platform.startswith("linux")
            or not self.mode.device.startswith("/dev/video")
        ):
            return
        controls: list[str] = []
        if self.mode.disable_dynamic_framerate:
            controls.append("exposure_dynamic_framerate=0")
        if self.mode.exposure_time_absolute is not None:
            controls.extend(
                (
                    "auto_exposure=1",
                    (
                        "exposure_time_absolute="
                        f"{self.mode.exposure_time_absolute}"
                    ),
                )
            )
        if not controls:
            return
        command = [
            "v4l2-ctl",
            "-d",
            self.mode.device,
            "--set-ctrl=" + ",".join(controls),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except FileNotFoundError:
            print(
                "WARNING: v4l2-ctl is not installed; "
                "camera exposure controls were not configured",
                file=sys.stderr,
                flush=True,
            )
            return
        except (OSError, subprocess.SubprocessError) as exc:
            print(
                "WARNING: unable to configure camera exposure controls: "
                f"{exc}",
                file=sys.stderr,
                flush=True,
            )
            return
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            suffix = f": {detail}" if detail else ""
            print(
                "WARNING: camera does not accept requested exposure controls "
                f"({','.join(controls)}){suffix}",
                file=sys.stderr,
                flush=True,
            )
            return
        print("Camera control: " + ", ".join(controls), flush=True)

    def open(self) -> None:
        if self._capture is not None:
            return
        capture = cv2.VideoCapture(
            self._capture_device(self.mode.device),
            cv2.CAP_V4L2,
        )
        if not capture.isOpened():
            capture.release()
            raise RuntimeIOError(f"无法打开相机 {self.mode.device}")

        capture.set(
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*self.mode.fourcc),
        )
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.mode.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.mode.height)
        capture.set(cv2.CAP_PROP_FPS, self.mode.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, self.mode.buffer_size)
        # Set this after the capture format because some UVC devices reset
        # exposure controls while changing resolution/FPS.
        self._configure_v4l2_frame_timing()

        actual_width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        actual_height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        actual_fps = float(capture.get(cv2.CAP_PROP_FPS))
        fourcc_value = int(round(capture.get(cv2.CAP_PROP_FOURCC)))
        actual_fourcc = "".join(
            chr((fourcc_value >> (8 * index)) & 0xFF)
            for index in range(4)
        )

        problems: list[str] = []
        if (actual_width, actual_height) != (self.mode.width, self.mode.height):
            problems.append(
                f"size={actual_width}x{actual_height}"
            )
        if actual_fps > 0 and abs(actual_fps - self.mode.fps) > 0.6:
            problems.append(f"fps={actual_fps:.2f}")
        if actual_fourcc.strip("\x00") and actual_fourcc != self.mode.fourcc:
            problems.append(f"fourcc={actual_fourcc!r}")
        if problems:
            capture.release()
            raise RuntimeIOError(
                "相机没有进入标定要求的模式：" + ", ".join(problems)
            )

        stop_event = threading.Event()
        reader_thread = threading.Thread(
            target=self._capture_loop,
            args=(capture, stop_event),
            name="fixed-usb-camera-reader",
            daemon=True,
        )
        with self._condition:
            self._capture = capture
            self._stop_event = stop_event
            self._reader_thread = reader_thread
            self._latest_frame = None
            self._latest_timestamp = None
            self._latest_sequence = 0
            self._delivered_sequence = 0
            self._reader_error = None
        try:
            reader_thread.start()
        except RuntimeError:
            with self._condition:
                self._capture = None
                self._reader_thread = None
                stop_event.set()
                self._condition.notify_all()
            capture.release()
            raise
        print(
            "Camera opened: "
            f"device={self.mode.device}; backend=V4L2; "
            f"mode={actual_width}x{actual_height}@{actual_fps:.2f}; "
            f"fourcc={actual_fourcc}; delivery=latest-frame-thread",
            flush=True,
        )

    def _capture_loop(
        self,
        capture: cv2.VideoCapture,
        stop_event: threading.Event,
    ) -> None:
        """Continuously capture and retain only the newest complete frame."""

        while not stop_event.is_set():
            try:
                ok, frame = capture.read()
                captured_monotonic = time.perf_counter()
            except Exception as exc:
                if stop_event.is_set():
                    return
                error = RuntimeIOError(f"读取相机帧失败：{exc}")
                with self._condition:
                    self._reader_error = error
                    self._condition.notify_all()
                return

            if stop_event.is_set():
                return
            if not ok or frame is None or frame.size == 0:
                with self._condition:
                    self._reader_error = RuntimeIOError("读取相机帧失败")
                    self._condition.notify_all()
                return

            with self._condition:
                if stop_event.is_set():
                    return
                self._latest_frame = frame
                self._latest_timestamp = captured_monotonic
                self._latest_sequence += 1
                self._condition.notify_all()

    def read(self) -> tuple[np.ndarray, float]:
        deadline = time.perf_counter() + self.mode.read_timeout_seconds
        with self._condition:
            if self._capture is None:
                raise RuntimeIOError("相机尚未打开")

            while self._latest_sequence <= self._delivered_sequence:
                if self._reader_error is not None:
                    raise self._reader_error
                if self._capture is None or self._stop_event.is_set():
                    raise RuntimeIOError("相机已关闭")
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise RuntimeIOError("等待最新相机帧超时")
                self._condition.wait(timeout=remaining)

            frame = self._latest_frame
            captured_monotonic = self._latest_timestamp
            if frame is None or captured_monotonic is None:
                raise RuntimeIOError("最新相机帧状态无效")
            self._delivered_sequence = self._latest_sequence
            return frame, captured_monotonic

    def warm_up(self, frame_count: int) -> None:
        for _ in range(max(0, int(frame_count))):
            self.read()

    def close(self) -> None:
        with self._condition:
            capture = self._capture
            reader_thread = self._reader_thread
            stop_event = self._stop_event
            self._capture = None
            self._reader_thread = None
            stop_event.set()
            self._condition.notify_all()

        if capture is None:
            return

        if reader_thread is not None:
            reader_thread.join(timeout=self.mode.read_timeout_seconds)
        capture.release()
        if reader_thread is not None and reader_thread.is_alive():
            reader_thread.join(timeout=self.mode.read_timeout_seconds)

    def __enter__(self) -> "FixedUSBCamera":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def _load_gimbal_comm() -> tuple[Any, Any]:
    source_root = WORKSPACE_ROOT / "gimbal_comm"
    if (source_root / "gimbal_comm" / "client.py").is_file():
        source_text = str(source_root)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
    try:
        from gimbal_comm import GimbalClient, GimbalCommConfig
    except ImportError as exc:
        raise RuntimeIOError(
            "无法导入 gimbal_comm；请保留工作区目录结构，或执行 "
            "python3 -m pip install -e ../../gimbal_comm"
        ) from exc
    return GimbalClient, GimbalCommConfig


@dataclass(frozen=True, slots=True)
class AngleReading:
    angle_deg: float
    received_monotonic: float
    age_seconds: float


PI_RX_SOF = 0xA5
STM32_TX_SOF = 0x5A
CMD_BALL_STATE = 0x07
CMD_TELEMETRY = 0x84
FLAG_TRACKING_VALID = 1 << 0

PI_FRAME = struct.Struct("<BBBHiiIB")
TELEMETRY_FRAME = struct.Struct("<BBBHiiiiIBB")


def _crc8(data: bytes, polynomial: int = 0x07, init: int = 0x00) -> int:
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ polynomial) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def _pack_ball_state(
    seq: int,
    pos_cm: float,
    vel_cm_s: float,
    valid: bool,
) -> bytes:
    flags = FLAG_TRACKING_VALID if valid else 0
    pi_time_ms = int(time.monotonic() * 1000.0) & 0xFFFFFFFF
    body_without_crc = PI_FRAME.pack(
        PI_RX_SOF,
        CMD_BALL_STATE,
        flags,
        seq & 0xFFFF,
        int(round(float(pos_cm) * 100.0)),
        int(round(float(vel_cm_s) * 100.0)),
        pi_time_ms,
        0,
    )[:-1]
    return body_without_crc + bytes((_crc8(body_without_crc),))


class _HtaskSerialClient:
    """Minimal client for the STM32 H-task 0xA5/0x5A UART protocol."""

    def __init__(
        self,
        port: str,
        baudrate: int,
        *,
        read_timeout_seconds: float,
        write_timeout_seconds: float,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.read_timeout_seconds = read_timeout_seconds
        self.write_timeout_seconds = write_timeout_seconds
        self.on_actual_angle = None
        self.latest_actual_angle = None
        self._serial: serial.Serial | None = None
        self._rx_buffer = bytearray()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._write_lock = threading.Lock()
        self._seq = 0
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._serial = serial.Serial(
            self.port,
            self.baudrate,
            timeout=self.read_timeout_seconds,
            write_timeout=self.write_timeout_seconds,
        )
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._reader_loop,
            name="HtaskSerialTelemetry",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._thread = None
        serial_port = self._serial
        self._serial = None
        if serial_port is not None and serial_port.is_open:
            serial_port.close()

    def get_link_status(self) -> Any:
        return SimpleNamespace(last_error=self._last_error)

    def request_telemetry(self) -> bool:
        return self.send_ball_state(0.0, 0.0, tracking_valid=False)

    def send_ball_state(
        self,
        ball_position_cm: float,
        ball_velocity_cm_s: float,
        *,
        tracking_valid: bool,
        wait_ack: bool = False,
    ) -> bool:
        del wait_ack
        serial_port = self._serial
        if serial_port is None or not serial_port.is_open:
            self._last_error = "串口未打开"
            return False
        frame = _pack_ball_state(
            self._seq,
            ball_position_cm,
            ball_velocity_cm_s,
            tracking_valid,
        )
        with self._write_lock:
            try:
                serial_port.write(frame)
            except serial.SerialException as exc:
                self._last_error = str(exc)
                return False
        self._seq = (self._seq + 1) & 0xFFFF
        return True

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            serial_port = self._serial
            if serial_port is None:
                break
            try:
                data = serial_port.read(128)
            except serial.SerialException as exc:
                self._last_error = str(exc)
                break
            if data:
                self._rx_buffer.extend(data)
                self._parse_available()

    def _parse_available(self) -> None:
        frame_size = TELEMETRY_FRAME.size
        while True:
            while self._rx_buffer and self._rx_buffer[0] != STM32_TX_SOF:
                del self._rx_buffer[0]
            if len(self._rx_buffer) < frame_size:
                return
            frame = bytes(self._rx_buffer[:frame_size])
            if _crc8(frame[:-1]) != frame[-1]:
                del self._rx_buffer[0]
                self._last_error = "遥测帧CRC错误"
                continue
            del self._rx_buffer[:frame_size]
            (
                sof,
                cmd,
                status,
                seq,
                rod_angle_001deg,
                motor_angle_001deg,
                motor_speed_001dps,
                motor_current_001a,
                stm32_time_ms,
                fault_code,
                _crc,
            ) = TELEMETRY_FRAME.unpack(frame)
            if sof != STM32_TX_SOF or cmd != CMD_TELEMETRY:
                self._last_error = "收到非遥测帧"
                continue
            del status, seq, rod_angle_001deg, motor_speed_001dps
            del motor_current_001a, stm32_time_ms, fault_code
            telemetry = SimpleNamespace(
                actual_angle_deg=motor_angle_001deg / 100.0,
                received_monotonic=time.perf_counter(),
            )
            self.latest_actual_angle = telemetry
            self._last_error = None
            callback = self.on_actual_angle
            if callback is not None:
                callback(telemetry)


def interpolate_angle_samples(
    history: tuple[tuple[float, float], ...],
    target_monotonic: float,
    maximum_age_seconds: float,
) -> AngleReading | None:
    """在按时间升序的 ``(timestamp, angle)`` 样本中插值角度。"""

    target = float(target_monotonic)
    maximum_age = float(maximum_age_seconds)
    if maximum_age <= 0:
        raise ValueError("maximum_age_seconds 必须为正数")
    if not history:
        return None

    before: tuple[float, float] | None = None
    after: tuple[float, float] | None = None
    for sample in history:
        if sample[0] <= target:
            before = sample
        elif after is None:
            after = sample
            break

    if before is not None and after is not None:
        span = after[0] - before[0]
        nearest_age = min(target - before[0], after[0] - target)
        if span > 1e-9 and nearest_age <= maximum_age:
            ratio = (target - before[0]) / span
            angle = before[1] + ratio * (after[1] - before[1])
            return AngleReading(
                angle_deg=float(angle),
                received_monotonic=target,
                age_seconds=float(nearest_age),
            )

    nearest = before if before is not None else after
    if nearest is None:
        return None
    age = abs(target - nearest[0])
    if age > maximum_age:
        return None
    return AngleReading(
        angle_deg=float(nearest[1]),
        received_monotonic=float(nearest[0]),
        age_seconds=float(age),
    )


class TelemetryAngleSource:
    """Read STM32 H-task telemetry angle from the current 0xA5/0x5A UART protocol."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        *,
        request_period_seconds: float = 0.02,
        link_timeout_seconds: float = 0.25,
        read_timeout_seconds: float = 0.01,
        write_timeout_seconds: float = 0.10,
        heartbeat_period_seconds: float = 0.10,
        reconnect_period_seconds: float = 0.50,
        history_samples: int = 256,
        estop_on_stop: bool = False,
    ) -> None:
        if request_period_seconds <= 0:
            raise ValueError("遥测请求周期必须为正数")
        timing_values = (
            link_timeout_seconds,
            read_timeout_seconds,
            write_timeout_seconds,
            heartbeat_period_seconds,
            reconnect_period_seconds,
        )
        if min(timing_values) <= 0 or not all(
            math.isfinite(value) for value in timing_values
        ):
            raise ValueError("串口与链路时序必须是有限正数")
        if history_samples < 2:
            raise ValueError("角度历史样本数必须至少为2")
        del heartbeat_period_seconds, reconnect_period_seconds, estop_on_stop
        self._client = _HtaskSerialClient(
            port=port,
            baudrate=baudrate,
            read_timeout_seconds=read_timeout_seconds,
            write_timeout_seconds=write_timeout_seconds,
        )
        self.request_period_seconds = float(request_period_seconds)
        self.link_timeout_seconds = float(link_timeout_seconds)
        self._next_request_at = 0.0
        self._history: deque[tuple[float, float]] = deque(maxlen=history_samples)
        self._history_lock = threading.Lock()
        self._client.on_actual_angle = self._record_telemetry

    def _record_telemetry(self, telemetry: Any) -> None:
        angle = float(telemetry.actual_angle_deg)
        received = float(telemetry.received_monotonic)
        if not math.isfinite(angle) or not math.isfinite(received):
            return
        with self._history_lock:
            self._history.append((received, angle))

    @property
    def client(self) -> Any:
        return self._client

    def start(self) -> None:
        self._client.start()

    def poll(self, now: float | None = None) -> None:
        current = time.perf_counter() if now is None else float(now)
        if current >= self._next_request_at:
            self._client.request_telemetry()
            self._next_request_at = current + self.request_period_seconds

    def wait_for_first_reading(self, timeout_seconds: float) -> AngleReading:
        deadline = time.perf_counter() + float(timeout_seconds)
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            self.poll(now)
            reading = self.latest(maximum_age_seconds=timeout_seconds)
            if reading is not None:
                return reading
            time.sleep(0.01)
        status = self._client.get_link_status()
        detail = status.last_error or "没有收到有效遥测帧"
        raise RuntimeIOError(f"等待 STM32 实际角度超时：{detail}")

    def latest(
        self,
        *,
        maximum_age_seconds: float,
        now: float | None = None,
    ) -> AngleReading | None:
        current = time.perf_counter() if now is None else float(now)
        telemetry = getattr(self._client, "latest_actual_angle", None)
        if telemetry is None:
            return None
        age = max(0.0, current - float(telemetry.received_monotonic))
        if age > maximum_age_seconds:
            return None
        angle = float(telemetry.actual_angle_deg)
        if not math.isfinite(angle):
            return None
        return AngleReading(
            angle_deg=angle,
            received_monotonic=float(telemetry.received_monotonic),
            age_seconds=age,
        )

    def angle_at(
        self,
        target_monotonic: float,
        *,
        maximum_age_seconds: float,
    ) -> AngleReading | None:
        """用相邻遥测插值得到指定相机时间戳对应的实际角度。"""

        target = float(target_monotonic)
        with self._history_lock:
            history = tuple(self._history)
        if not history:
            return self.latest(
                maximum_age_seconds=maximum_age_seconds,
                now=target,
            )

        return interpolate_angle_samples(
            history,
            target,
            maximum_age_seconds,
        )

    def stop(self) -> None:
        self._client.stop()

    def __enter__(self) -> "TelemetryAngleSource":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()
