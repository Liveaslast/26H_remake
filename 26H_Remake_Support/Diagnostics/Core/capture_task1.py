"""Capture the firmware-encapsulated Task1 sequence.

The host sends only ``task 1``.  Task parameters and the 0 -> +5 -> -5
sequence are owned by the STM32 BallBeamController.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import serial

SUPPORT_ROOT = Path(__file__).resolve().parents[2]
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from Diagnostics.Core.ballbeam_capture import (
    HEADER,
    capture_device_sequence,
    unique_output_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture firmware Task1: 0 -> +5 -> -5")
    parser.add_argument("--port", default="COM26")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--output", default="seq_task1.csv")
    # Includes the automatic return to x=0 when a previous Task1 ended at -5.
    parser.add_argument("--capture-s", type=float, default=12.0)
    parser.add_argument("--print-ms", type=float, default=300.0)
    parser.add_argument(
        "--bbp-short",
        nargs=4,
        type=float,
        metavar=("KP", "MARGIN_CM", "MAX_DEG", "DIST_CM"),
        help=(
            "after 'task 1', override the short-move brake profile through "
            "the existing serial command: bbp KP MARGIN_CM MAX_DEG DIST_CM"
        ),
    )
    parser.add_argument(
        "--bbp-long",
        nargs=4,
        type=float,
        metavar=("KP", "MARGIN_CM", "MAX_DEG", "DIST_CM"),
        help=(
            "after 'task 1', override the long-move brake profile through "
            "the existing serial command: bbpd KP MARGIN_CM MAX_DEG DIST_CM"
        ),
    )
    parser.add_argument(
        "--bbp-negative-max",
        type=float,
        metavar="MAX_DEG",
        help=(
            "after 'task 1', override the negative-move brake limit through "
            "the existing serial command: bbpn MAX_DEG"
        ),
    )
    parser.add_argument(
        "--bpush-positive",
        nargs=4,
        type=float,
        metavar=("WINDOW_CM", "VX_CM_S", "PUSH_DEG", "MAX_DEG"),
        help=(
            "after 'task 1', override only the positive terminal push through "
            "the existing serial command: bpushp WINDOW_CM VX_CM_S PUSH_DEG MAX_DEG"
        ),
    )
    parser.add_argument(
        "--bpush-negative",
        nargs=4,
        type=float,
        metavar=("WINDOW_CM", "VX_CM_S", "PUSH_DEG", "MAX_DEG"),
        help=(
            "after 'task 1', override only the negative terminal push through "
            "the existing serial command: bpushm WINDOW_CM VX_CM_S PUSH_DEG MAX_DEG"
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.bbp_short is not None and any(value < 0.0 for value in args.bbp_short):
        parser.error("--bbp-short values must be non-negative")
    if args.bbp_long is not None and any(value < 0.0 for value in args.bbp_long):
        parser.error("--bbp-long values must be non-negative")
    if args.bbp_negative_max is not None and args.bbp_negative_max < 0.0:
        parser.error("--bbp-negative-max must be non-negative")
    if args.bpush_positive is not None and any(
        value < 0.0 for value in args.bpush_positive
    ):
        parser.error("--bpush-positive values must be non-negative")
    if args.bpush_negative is not None and any(
        value < 0.0 for value in args.bpush_negative
    ):
        parser.error("--bpush-negative values must be non-negative")

    output = unique_output_path(args.output, args.overwrite)
    rows = []

    with serial.Serial(args.port, args.baudrate, timeout=0.2) as ser:
        print(f"open {args.port} @ {args.baudrate} -> {output}", flush=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=HEADER)
            writer.writeheader()

            print("command: > task 1", flush=True)
            ser.write(b"task 1\r\n")
            ser.flush()

            if args.bbp_short is not None:
                kp, margin_cm, max_deg, dist_cm = args.bbp_short
                command = f"bbp {kp:g} {margin_cm:g} {max_deg:g} {dist_cm:g}"
                print(f"command: > {command}", flush=True)
                ser.write((command + "\r\n").encode("ascii"))
                ser.flush()

            if args.bbp_long is not None:
                kp, margin_cm, max_deg, dist_cm = args.bbp_long
                command = f"bbpd {kp:g} {margin_cm:g} {max_deg:g} {dist_cm:g}"
                print(f"command: > {command}", flush=True)
                ser.write((command + "\r\n").encode("ascii"))
                ser.flush()

            if args.bbp_negative_max is not None:
                command = f"bbpn {args.bbp_negative_max:g}"
                print(f"command: > {command}", flush=True)
                ser.write((command + "\r\n").encode("ascii"))
                ser.flush()

            if args.bpush_positive is not None:
                window_cm, vx_cm_s, push_deg, max_deg = args.bpush_positive
                command = (
                    f"bpushp {window_cm:g} {vx_cm_s:g} {push_deg:g} {max_deg:g}"
                )
                print(f"command: > {command}", flush=True)
                ser.write((command + "\r\n").encode("ascii"))
                ser.flush()

            if args.bpush_negative is not None:
                window_cm, vx_cm_s, push_deg, max_deg = args.bpush_negative
                command = (
                    f"bpushm {window_cm:g} {vx_cm_s:g} {push_deg:g} {max_deg:g}"
                )
                print(f"command: > {command}", flush=True)
                ser.write((command + "\r\n").encode("ascii"))
                ser.flush()

            time.sleep(0.05)

            start_time = time.monotonic()
            try:
                capture_device_sequence(
                    ser, writer, rows, start_time, args.capture_s, args.print_ms
                )
            finally:
                # Ctrl+C must not leave the previous task latched in the MCU.
                try:
                    ser.write(b"task stop\r\n")
                    ser.flush()
                except serial.SerialException:
                    pass

    print(f"capture_done samples={len(rows)} output={output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
