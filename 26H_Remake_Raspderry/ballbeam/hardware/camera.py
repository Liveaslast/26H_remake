"""USB camera parameters and latest-frame capture."""
## 相机配置太长了，懒得看。。。

from __future__ import annotations

from dataclasses import dataclass
import math
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

from ..errors import RuntimeIOError


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
