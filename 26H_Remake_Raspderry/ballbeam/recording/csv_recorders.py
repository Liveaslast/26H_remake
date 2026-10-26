"""CSV recorders for MCU telemetry, Pi packets and vision diagnostics."""

from __future__ import annotations

import math
from pathlib import Path
import threading
import time
from typing import Any

from ..vision.tracker import DynamicTrackingResult
from ..communication.protocol import Mode
from .csv_writer import CsvWriter


class Task1CsvLogger:
    """Record decoded MCU control samples during a fixed capture window."""

    _HEADER = (
        "t_s", "phase", "ab_x", "target_x", "ab_v", "angle",
        "target_angle", "seq_stage", "age_ms", "stm32_ms", "frame_seq", "vision_seq",
        "control_ms", "control_x", "control_v", "target_v",
    )

    def __init__(self, path: Path, *, duration_seconds: float = 5.0,
                 label: str = "Task1", worker=None) -> None:
        if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
            raise ValueError("Task1 capture duration must be positive")
        self.path = path
        self.label = label
        self.duration_seconds = duration_seconds
        self.output = CsvWriter(path, self._HEADER, worker=worker)
        self._first_ms: int | None = None
        self._last_seq: int | None = None
        self.gaps = 0
        self._recording = False
        self._closed = False
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        with self._lock:
            if self._closed or self._recording:
                return
            self._recording = True
            self._timer = threading.Timer(self.duration_seconds, self._finish_capture)
            self._timer.daemon = True
            self._timer.start()

    def publish(self, sample: Any) -> None:
        with self._lock:
            if not self._recording or self._closed:
                return
            ms = int(sample.stm32_time_ms)
            if self._first_ms is None:
                self._first_ms = ms
            seq = int(sample.seq)
            if self._last_seq is not None:
                self.gaps += max(0, ((seq - self._last_seq) & 0xFFFF) - 1)
            self._last_seq = seq
            target = float(sample.target_x)
            phase = ("speed_step" if sample.seq_stage == 10 else
                     "speed_done" if sample.seq_stage == 12 else
                     "speed_abort" if sample.seq_stage == 13 else
                     "minus5" if target < -0.5 else ("plus5" if target > 0.5 else "home"))
            self.output.write((
                ((ms - self._first_ms) & 0xFFFFFFFF) / 1000.0,
                phase, sample.ab_x, target, sample.ab_v, sample.angle,
                sample.target_angle,
                sample.seq_stage, sample.age_ms, ms, seq, sample.vision_seq,
                sample.control_tick_ms, sample.control_x, sample.control_v,
                sample.target_v,
            ))

    @property
    def samples(self):
        return self.output.rows_written

    def _finish_capture(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._recording = False
            self._closed = True
        self.output.close()

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._closed and self.output.closed

    def close(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            if not self._closed:
                self._recording = False
                self._closed = True
        self.output.close()


class BallStateTxLogger:
    """Format decoded task/debug packets written to the Pi serial port."""

    _HEADER = (
        "seq", "pi_time_ms", "write_done_t", "position_001cm",
        "velocity_001cms", "tracking_valid", "task_request_id", "capture_requested",
        "request_seq", "mode",
    )

    def __init__(self, path: Path, *, worker=None) -> None:
        self.path = path
        self.output = CsvWriter(path, self._HEADER, worker=worker)

    @property
    def samples(self):
        return self.output.rows_written

    def publish(self, packet, write_done_t: float) -> None:
        self.output.write((
            packet.seq, packet.pi_time_ms, f"{write_done_t:.6f}",
            packet.position_001cm, packet.velocity_001cms,
            int(packet.tracking_valid), packet.task_id, int(packet.mode == Mode.TUNING),
            packet.request_seq, int(packet.mode),
        ))

    def close(self) -> None:
        self.output.close()


class VisionProbeLogger:
    """Record tracker output alongside the submitted ball measurements."""

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
        worker=None,
    ) -> None:
        self.path = path
        self.print_rows = print_rows
        self.output = None if path is None else CsvWriter(path, self._HEADER, worker=worker)
        self._frame_seq = 0

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
        if self.output is not None:
            self.output.write(row)
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
        if self.output is not None:
            self.output.close()
