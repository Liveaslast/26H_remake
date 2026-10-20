"""Optional debug-page, MJPEG streaming and missing-angle overlays."""

import argparse
import math
from typing import Any

import cv2

from ..errors import RuntimeIOError
from ..vision.tracker import DynamicTrackingResult, draw_tracking_overlay


class VisionReporter:
    """Own console reporting cadence; consume, never calculate, statistics."""

    def __init__(self, period_seconds):
        self.period_seconds = period_seconds
        self.next_report = 0.0

    def report(self, now, result, decision, metrics):
        if now >= self.next_report:
            print(decision.report_prefix + format_result(result, fps=metrics.fps)
                  + " " + format_vision_stats(metrics), flush=True)
            self.next_report = now + self.period_seconds


class TrackingDisplay:
    """Own the local window, fallback canvas and keyboard handling."""

    def __init__(self, window_name, *, enabled=True, fallback_overlay=None,
                 decorate_overlay=None, key_handler=None, hold_last=False):
        self.window_name = window_name
        self.enabled = enabled
        self.fallback_overlay = fallback_overlay
        self.decorate_overlay = decorate_overlay
        self.key_handler = key_handler
        self.hold_last = hold_last
        self.last_canvas = None

    def show(self, frame, result, decision, fps):
        """Return False on Q/Escape; disabled display never accesses HighGUI."""
        if not self.enabled:
            return True
        canvas = draw_tracking_overlay(result, fps=fps)
        if canvas is None:
            canvas = (self.last_canvas.copy()
                      if self.hold_last and self.last_canvas is not None else frame)
            if self.fallback_overlay is not None:
                canvas = self.fallback_overlay(canvas, result, fps)
        else:
            self.last_canvas = canvas.copy()
        if self.decorate_overlay is not None:
            canvas = self.decorate_overlay(canvas, decision, fps)
        cv2.imshow(self.window_name, canvas)
        key = cv2.waitKeyEx(1)
        if key in (ord("q"), ord("Q"), 27):
            return False
        if self.key_handler is not None:
            self.key_handler(key)
        return True

    def close(self):
        if self.enabled:
            cv2.destroyAllWindows()


def start_debug_page(
    *,
    host: str,
    port: int,
    max_points: int,
) -> Any:
    """Lazily start DebugPage so normal operation does not require Flask."""

    try:
        from .debug_page import DebugPage
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


## 角度数据异常时绘制警告
def draw_missing_angle(
    frame,
    result: DynamicTrackingResult,
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


## 启动WIFI MHPEG图传
def start_wifi_stream(args: argparse.Namespace):
    """Start WIFI_test in-process so tracking remains the only camera owner."""

    try:
        from .wifi_stream.mjpeg_stream import (
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


def format_result(
    result: DynamicTrackingResult,
    *,
    fps: float | None = None,
) -> str:
    display_position = (
        result.measurement_position_cm
        if result.measurement_valid and result.measurement_position_cm is not None
        else result.position_cm
    )
    x = "none" if display_position is None else f"{display_position:+.3f}"
    vx = (
        "none"
        if result.velocity_cm_s is None
        else f"{result.velocity_cm_s:+.2f}"
    )
    angle = (
        "none"
        if result.actual_angle_deg is None
        else f"{result.actual_angle_deg:+.3f}"
    )
    lost_ms = (
        "none"
        if result.lost_seconds is None
        else f"{result.lost_seconds * 1000.0:.1f}"
    )
    fps_text = "warming" if fps is None else f"{fps:.1f}"
    return (
        f"x={x}cm vx={vx}cm/s angle={angle}deg "
        f"valid={result.tracking_valid} "
        f"measurement={result.measurement_valid} "
        f"source={result.source} confidence={result.confidence:.2f} "
        f"lost={lost_ms}ms processing={result.processing_ms:.2f}ms "
        f"fps={fps_text} reason={result.reason}"
    )


def format_vision_stats(metrics) -> str:
    def number(value, unit=""):
        return "warming" if value is None else f"{value:.2f}{unit}"

    return (f"valid_detect_hz={number(metrics.valid_detection_hz)} "
            f"avg_infer={number(metrics.average_inference_ms, 'ms')} "
            f"avg_total={number(metrics.average_processing_ms, 'ms')}")


def publish_debug_state(page, result, state):
    if page is None:
        return
    values = {
        "ball_position_cm": state.position_cm,
        "ball_velocity_cm_s": state.velocity_cm_s,
        "tracking_valid": float(state.valid),
    }
    if result.actual_angle_deg is not None and math.isfinite(result.actual_angle_deg):
        values["actual_angle_deg"] = float(result.actual_angle_deg)
    page.publish(values)


def report_capture_finished(control):
    """Present recording results without embedding machine-specific copy commands."""
    print(
        f"{control.label} CSV 采集完成：{control.duration_seconds:g}s "
        f"samples={control.samples} gaps={control.gaps} path={control.path}；"
        "视觉继续运行，按 Ctrl+C 后手动复位下位机。",
        flush=True,
    )
