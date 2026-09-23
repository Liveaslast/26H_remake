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
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

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
