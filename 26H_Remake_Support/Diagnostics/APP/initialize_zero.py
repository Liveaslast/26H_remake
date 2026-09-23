"""Initialize the BallBeam zero point once after reset or flashing."""

from __future__ import annotations

import argparse
import time

import serial


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set BallBeam zero point and balance angle 22 degrees"
    )
    parser.add_argument("--port", default="COM26")
    parser.add_argument("--baudrate", type=int, default=115200)
    args = parser.parse_args()

    print("WARNING: mechanically place the system at the zero point first.")
    input("Press Enter to send task init...")

    with serial.Serial(args.port, args.baudrate, timeout=0.2) as ser:
        print(f"open {args.port} @ {args.baudrate}", flush=True)
        print("command: > task init", flush=True)
        ser.write(b"task init\r\n")
        ser.flush()
        time.sleep(0.3)

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if line:
                print(line, flush=True)

    print("initialize_done: zero point set, balance angle set to 22 deg")
    print("Do not run this script again unless the MCU was reset/flashed or the mechanical zero changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
