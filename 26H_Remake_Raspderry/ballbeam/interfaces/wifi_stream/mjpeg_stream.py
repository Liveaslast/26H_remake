#!/usr/bin/env python3
"""Non-blocking MJPEG streaming for the fixed USB camera.

The tracking loop remains the only owner of ``/dev/video0``.  It publishes its
latest BGR frame to :class:`MJPEGStreamServer`; a background encoder drops old
frames as needed and HTTP client threads serve the newest JPEG without blocking
camera capture or control.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import cv2
import numpy as np

from ...hardware.runtime import (
    CameraMode,
    FixedUSBCamera,
    RuntimeIOError,
)


STREAM_PATH = "/stream.mjpg"
HEALTH_PATH = "/healthz"
BOUNDARY = "frame"


class MJPEGStreamError(RuntimeError):
    """The MJPEG encoder or HTTP server could not operate."""


@dataclass(frozen=True, slots=True)
class MJPEGStreamConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    width: int = 640
    height: int = 360
    fps: float = 20.0
    jpeg_quality: int = 75

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("图传监听地址不能为空")
        if not 0 <= int(self.port) <= 65535:
            raise ValueError("图传端口必须在 0..65535 内")
        if int(self.width) < 2 or int(self.height) < 2:
            raise ValueError("图传分辨率无效")
        if not math.isfinite(float(self.fps)) or float(self.fps) <= 0:
            raise ValueError("图传帧率必须为正数")
        if not 1 <= int(self.jpeg_quality) <= 100:
            raise ValueError("JPEG 质量必须在 1..100 内")


class _MJPEGHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    block_on_close = False

    def __init__(
        self,
        address: tuple[str, int],
        owner: "MJPEGStreamServer",
    ) -> None:
        self.owner = owner
        super().__init__(address, _MJPEGRequestHandler)


class _MJPEGRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BallCamMJPEG/1.0"

    @property
    def owner(self) -> "MJPEGStreamServer":
        server = self.server
        if not isinstance(server, _MJPEGHTTPServer):
            raise RuntimeError("无效的 MJPEG HTTP server")
        return server.owner

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/":
            self._serve_index()
        elif path == STREAM_PATH:
            self._serve_stream()
        elif path == HEALTH_PATH:
            self._serve_health()
        else:
            self.send_error(404, "Not Found")

    def _serve_index(self) -> None:
        body = (
            "<!doctype html><html><head>"
            "<meta charset='utf-8'>"
            "<meta name='viewport' "
            "content='width=device-width,initial-scale=1'>"
            "<title>Ball Camera</title>"
            "<style>html,body{margin:0;background:#000;height:100%;}"
            "body{display:flex;align-items:center;justify-content:center;}"
            "img{max-width:100%;max-height:100%;object-fit:contain;}</style>"
            "</head><body>"
            f"<img src='{STREAM_PATH}' alt='Ball camera stream'>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_health(self) -> None:
        body = json.dumps(
            self.owner.stats(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_stream(self) -> None:
        self.send_response(200)
        self.send_header(
            "Content-Type",
            f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        )
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        self.connection.settimeout(2.0)
        sequence = -1
        self.owner._client_opened()
        try:
            while self.owner.running:
                jpeg, sequence = self.owner.wait_for_jpeg(
                    after_sequence=sequence,
                    timeout_seconds=1.0,
                )
                if jpeg is None:
                    continue
                header = (
                    f"--{BOUNDARY}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n"
                    "\r\n"
                ).encode("ascii")
                self.wfile.write(header)
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            self.owner._client_closed()


class MJPEGStreamServer:
    """Serve the newest published frame while dropping stale frames."""

    def __init__(self, config: MJPEGStreamConfig) -> None:
        self.config = config
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._running = False
        self._latest_frame: np.ndarray | None = None
        self._published_sequence = 0
        self._latest_jpeg: bytes | None = None
        self._encoded_sequence = 0
        self._clients = 0
        self._encode_failures = 0
        self._httpd: _MJPEGHTTPServer | None = None
        self._encoder_thread: threading.Thread | None = None
        self._http_thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        with self._condition:
            return self._running

    @property
    def bound_port(self) -> int:
        httpd = self._httpd
        return self.config.port if httpd is None else int(httpd.server_port)

    def start(self) -> None:
        with self._condition:
            if self._running:
                return
        try:
            httpd = _MJPEGHTTPServer(
                (self.config.host, self.config.port),
                self,
            )
        except OSError as exc:
            raise MJPEGStreamError(
                f"无法监听 {self.config.host}:{self.config.port}：{exc}"
            ) from exc

        with self._condition:
            self._httpd = httpd
            self._stop_event.clear()
            self._running = True
        self._encoder_thread = threading.Thread(
            target=self._encoder_loop,
            name="mjpeg-encoder",
            daemon=True,
        )
        self._http_thread = threading.Thread(
            target=httpd.serve_forever,
            kwargs={"poll_interval": 0.20},
            name="mjpeg-http",
            daemon=True,
        )
        self._encoder_thread.start()
        self._http_thread.start()

    def publish(self, frame: np.ndarray) -> None:
        """Publish a BGR/gray uint8 frame without waiting for JPEG clients."""

        if not isinstance(frame, np.ndarray) or frame.size == 0:
            raise ValueError("图传帧不能为空")
        if frame.dtype != np.uint8 or frame.ndim not in (2, 3):
            raise ValueError("图传帧必须是 uint8 灰度或彩色图像")
        if frame.ndim == 3 and frame.shape[2] not in (3, 4):
            raise ValueError("彩色图传帧必须包含 3 或 4 个通道")
        with self._condition:
            if not self._running:
                raise MJPEGStreamError("MJPEG 服务尚未启动")
            self._latest_frame = frame
            self._published_sequence += 1
            self._condition.notify_all()

    def wait_for_jpeg(
        self,
        *,
        after_sequence: int,
        timeout_seconds: float,
    ) -> tuple[bytes | None, int]:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._condition:
            while (
                self._running
                and (
                    self._latest_jpeg is None
                    or self._encoded_sequence <= after_sequence
                )
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._latest_jpeg, self._encoded_sequence

    def stats(self) -> dict[str, int | float | bool]:
        with self._condition:
            return {
                "running": self._running,
                "published_frames": self._published_sequence,
                "encoded_frames": self._encoded_sequence,
                "encode_failures": self._encode_failures,
                "clients": self._clients,
                "stream_width": self.config.width,
                "stream_height": self.config.height,
                "stream_fps_limit": self.config.fps,
                "jpeg_quality": self.config.jpeg_quality,
            }

    def stop(self) -> None:
        with self._condition:
            if not self._running and self._httpd is None:
                return
            self._running = False
            self._condition.notify_all()
        self._stop_event.set()

        httpd = self._httpd
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        for thread in (self._encoder_thread, self._http_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self._httpd = None
        self._encoder_thread = None
        self._http_thread = None

    def _encoder_loop(self) -> None:
        period = 1.0 / self.config.fps
        next_encode_at = time.perf_counter()
        consumed_sequence = 0
        while not self._stop_event.is_set():
            with self._condition:
                while (
                    self._running
                    and self._published_sequence <= consumed_sequence
                ):
                    self._condition.wait(timeout=0.25)
                if not self._running:
                    return

            delay = next_encode_at - time.perf_counter()
            if delay > 0 and self._stop_event.wait(delay):
                return

            with self._condition:
                if not self._running or self._latest_frame is None:
                    continue
                frame = self._latest_frame.copy()
                consumed_sequence = self._published_sequence

            try:
                prepared = self._prepare_frame(frame)
                ok, encoded = cv2.imencode(
                    ".jpg",
                    prepared,
                    [cv2.IMWRITE_JPEG_QUALITY, self.config.jpeg_quality],
                )
            except cv2.error:
                ok = False
                encoded = None

            with self._condition:
                if ok and encoded is not None:
                    self._latest_jpeg = encoded.tobytes()
                    self._encoded_sequence += 1
                    self._condition.notify_all()
                else:
                    self._encode_failures += 1

            completed = time.perf_counter()
            next_encode_at = max(next_encode_at + period, completed)

    def _prepare_frame(self, frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        target = (self.config.width, self.config.height)
        if (frame.shape[1], frame.shape[0]) == target:
            return frame
        interpolation = (
            cv2.INTER_AREA
            if frame.shape[1] >= target[0] and frame.shape[0] >= target[1]
            else cv2.INTER_LINEAR
        )
        return cv2.resize(frame, target, interpolation=interpolation)

    def _client_opened(self) -> None:
        with self._condition:
            self._clients += 1

    def _client_closed(self) -> None:
        with self._condition:
            self._clients = max(0, self._clients - 1)

    def __enter__(self) -> "MJPEGStreamServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()


def _positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return value


def _positive_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("必须是正的有限数值")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="独占 USB 摄像头并通过 HTTP 输出低延迟 MJPEG 图传。",
    )
    parser.add_argument("--camera", default="/dev/video0")
    parser.add_argument("--width", type=_positive_int, default=1280)
    parser.add_argument("--height", type=_positive_int, default=720)
    parser.add_argument("--fps", type=_positive_float, default=60.0)
    parser.add_argument("--warmup-frames", type=int, default=10)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=_positive_int, default=8080)
    parser.add_argument("--stream-width", type=_positive_int, default=640)
    parser.add_argument("--stream-height", type=_positive_int, default=360)
    parser.add_argument("--stream-fps", type=_positive_float, default=20.0)
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        choices=range(1, 101),
        default=75,
        metavar="1..100",
    )
    return parser


def run_standalone(args: argparse.Namespace) -> int:
    if args.warmup_frames < 0:
        raise ValueError("--warmup-frames 不能为负数")
    camera = FixedUSBCamera(
        CameraMode(
            device=args.camera,
            width=args.width,
            height=args.height,
            fps=args.fps,
            fourcc="MJPG",
        )
    )
    stream = MJPEGStreamServer(
        MJPEGStreamConfig(
            host=args.host,
            port=args.port,
            width=args.stream_width,
            height=args.stream_height,
            fps=args.stream_fps,
            jpeg_quality=args.jpeg_quality,
        )
    )
    captured = 0
    report_started = time.perf_counter()
    try:
        camera.open()
        camera.warm_up(args.warmup_frames)
        stream.start()
        print(
            "MJPEG ready: "
            f"http://192.168.50.1:{stream.bound_port}/ "
            f"(VLC: http://192.168.50.1:{stream.bound_port}{STREAM_PATH})",
            flush=True,
        )
        while True:
            frame, _timestamp = camera.read()
            stream.publish(frame)
            captured += 1
            now = time.perf_counter()
            if now - report_started >= 2.0:
                stats = stream.stats()
                print(
                    f"capture={captured / (now - report_started):.1f}fps; "
                    f"encoded={stats['encoded_frames']}; "
                    f"clients={stats['clients']}; "
                    f"failures={stats['encode_failures']}",
                    flush=True,
                )
                captured = 0
                report_started = now
    finally:
        stream.stop()
        camera.close()


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run_standalone(args)
    except KeyboardInterrupt:
        print("\nMJPEG stream stopped.", flush=True)
        return 130
    except (MJPEGStreamError, RuntimeIOError, ValueError, cv2.error) as exc:
        print(f"MJPEG stream failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
