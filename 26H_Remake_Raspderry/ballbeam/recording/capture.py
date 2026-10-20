"""Coordinate optional CSV captures and their shared recording window."""

import json

from .csv_recorders import BallStateTxLogger, Task1CsvLogger, VisionProbeLogger
from .csv_writer import CsvWriteWorker

"""
CSV数据采集的管理器:
    管理各种CSV数据：协调各种视觉数据、控制数据、以及启动参数
此处往下即可具体地了解目前项目的数据分析的分析对象、分析目的、分析过程等。。暂不展开
"""
class CaptureSession:
    def __init__(self, args, *, label="Task1"):
        self.args = args
        self.label = label
        self.control = None
        self.sent = None
        self.probe = None
        self.writer = None
        self._window_finished = False

    def open(self):
        args = self.args
        if args.task1_csv is not None or args.vision_probe_csv is not None:
            self.writer = CsvWriteWorker()
        if args.task1_csv is not None:
            self.control = Task1CsvLogger(
                args.task1_csv, duration_seconds=args.task1_capture_s,
                label=self.label,
                worker=self.writer,
            )
            self.sent = BallStateTxLogger(args.task1_csv.with_name("ball_state_tx.csv"), worker=self.writer)
            print(f"BALL_STATE TX CSV: {self.sent.path}", flush=True)
        if args.vision_probe_csv is not None or args.vision_probe_print:
            self.probe = VisionProbeLogger(
                path=args.vision_probe_csv, print_rows=args.vision_probe_print,
                worker=self.writer,
            )
            if args.vision_probe_csv is not None:
                print(f"Vision probe CSV: {args.vision_probe_csv}", flush=True)

    def start(self):
        if self.control is not None:
            self.control.start()

    def finish_if_needed(self):
        """Close companion logs once the control window ends; report the transition."""
        if self.control is None or not self.control.finished or self._window_finished:
            return False
        self._window_finished = True
        self.sent.close()
        if self.probe is not None:
            self.probe.close()
            self.probe = None
        return True

    def record_vision(self, result, state):
        if self.probe is not None:
            self.probe.publish(
                result=result, sent_position_cm=state.position_cm,
                sent_velocity_cm_s=state.velocity_cm_s, sent_valid=state.valid,
            )

    def save_settings(self, filename, settings):
        """Save experiment metadata supplied by the application, without interpreting it."""
        self.args.task1_csv.with_name(filename).write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8",
        )

    def close(self):
        if self.probe is not None:
            self.probe.close()
        if self.sent is not None:
            self.sent.close()
        if self.control is not None:
            self.control.close()
            print(f"Task1 CSV saved: {self.control.path} samples={self.control.samples} "
                  f"gaps={self.control.gaps}", flush=True)
        if self.writer is not None:
            self.writer.close()
