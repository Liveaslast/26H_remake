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

    print("Running task1: 0 -> +5 -> -5 -> stop", flush=True)
    return subprocess.run(command, cwd=SUPPORT_ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
