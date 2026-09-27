"""Run the firmware-encapsulated Task1 0 -> +5 -> -5 sequence."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SUPPORT_ROOT = Path(__file__).resolve().parents[2]
CAPTURE = SUPPORT_ROOT / "Diagnostics" / "Core" / "capture_task1.py"
DEFAULT_OUTPUT = SUPPORT_ROOT / "Data" / "TestRecords" / "task1_latest.csv"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run fixed task1: 0 -> +5 -> -5 and stop"
    )
    parser.add_argument("--port", default="COM26")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--bbp-short",
        nargs=4,
        type=float,
        metavar=("KP", "MARGIN_CM", "MAX_DEG", "DIST_CM"),
        help="override the short-move BBP profile after Task1 starts",
    )
    parser.add_argument(
        "--bbp-long",
        nargs=4,
        type=float,
        metavar=("KP", "MARGIN_CM", "MAX_DEG", "DIST_CM"),
        help="override the long-move BBP profile after Task1 starts",
    )
    parser.add_argument(
        "--bbp-negative-max",
        type=float,
        metavar="MAX_DEG",
        help="override the negative-move BBP angle limit after Task1 starts",
    )
    parser.add_argument(
        "--bpush-positive",
        nargs=4,
        type=float,
        metavar=("WINDOW_CM", "VX_CM_S", "PUSH_DEG", "MAX_DEG"),
        help="override only the positive terminal push after Task1 starts",
    )
    parser.add_argument(
        "--bpush-negative",
        nargs=4,
        type=float,
        metavar=("WINDOW_CM", "VX_CM_S", "PUSH_DEG", "MAX_DEG"),
        help="override only the negative terminal push after Task1 starts",
    )
    args = parser.parse_args()

    output = Path(args.output)
    if not output.is_absolute():
        output = SUPPORT_ROOT / output

    command = [
        sys.executable,
        str(CAPTURE),
        "--port",
        args.port,
        "--baudrate",
        str(args.baudrate),
        "--output",
        str(output),
        "--overwrite",
    ]
    if args.bbp_short is not None:
        command.extend(["--bbp-short", *(f"{value:g}" for value in args.bbp_short)])
    if args.bbp_long is not None:
        command.extend(["--bbp-long", *(f"{value:g}" for value in args.bbp_long)])
    if args.bbp_negative_max is not None:
        command.extend(["--bbp-negative-max", f"{args.bbp_negative_max:g}"])
    if args.bpush_positive is not None:
        command.extend(
            [
                "--bpush-positive",
                *(f"{value:g}" for value in args.bpush_positive),
            ]
        )
    if args.bpush_negative is not None:
        command.extend(
            [
                "--bpush-negative",
                *(f"{value:g}" for value in args.bpush_negative),
            ]
        )

    print("Running task1: 0 -> +5 -> -5 -> stop", flush=True)
    return subprocess.run(command, cwd=SUPPORT_ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
