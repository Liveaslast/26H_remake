#!/usr/bin/env python3
"""Capture the current STM32 BallBeam debug stream with host timestamps.

This script matches DebugTask.cpp in 26H_Remake_DJC.  The firmware emits one
strict 13-field CSV sample every 5 ms.  No position or velocity processing is
performed here; host-side timing and hold-duration diagnostics are appended.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys
import time
from typing import TextIO


FIRMWARE_FIELDS = [
    "estimated_x_cm",
    "target_x_cm",
    "estimated_vx_cm_s",
    "motor_angle_deg",
    "angle_command_deg",
    "brake_p_offset_deg",
    "terminal_offset_deg",
    "brake_p_active",
    "terminal_push_active",
    "terminal_trim_active",
    "terminal_brake_gate_active",
    "sequence_stage",
    "vision_age_ms",
]

VISION_FIELDS = [
    "stm32_time_ms",
    "rx_present",
    "rx_seq",
    "pi_time_ms",
    "tracking_valid",
    "rx_age_ms",
    "packet_x_cm",
    "estimate_valid",
    "accepted_raw_x_cm",
    "estimated_x_cm",
    "estimated_vx_cm_s",
    "vision_age_ms",
]

INTEGER_FIELD_INDEXES = set(range(7, 13))

CSV_FIELDS = [
    "host_iso8601",
    "host_unix_ns",
    "elapsed_s",
    "rx_interval_ms",
    "record_type",
    "stm32_time_ms",
    "rx_present",
    "rx_seq",
    "pi_time_ms",
    "tracking_valid",
    "rx_age_ms",
    "packet_x_cm",
    "estimate_valid",
    "accepted_raw_x_cm",
    *FIRMWARE_FIELDS,
    "x_changed",
    "x_unchanged_ms",
    "raw_line",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture STM32 13-field BallBeam CSV with host timestamps. "
            "Close VOFA/other serial programs before starting."
        )
    )
    parser.add_argument("--port", default="COM26", help="STM32 debug serial port")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument(
        "--mode",
        choices=("listen", "ba22", "task1"),
        default="listen",
        help=(
            "listen: capture only; ba22: send 'ba 22'; "
            "task1: send 'task 1' and always send 'task stop' on exit"
        ),
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=30.0,
        help="capture duration; 0 means until Ctrl+C",
    )
    parser.add_argument(
        "--firmware-csv",
        choices=("unchanged", "vision", "control", "off"),
        default="vision",
        help="select STM32 debug output mode; vision is the latency diagnostic mode",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "output CSV; default: "
            "Data/TestRecords/mcu_vision_<mode>_<timestamp>.csv"
        ),
    )
    parser.add_argument("--report-s", type=float, default=1.0)
    parser.add_argument("--flush-s", type=float, default=0.5)
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="list serial ports and exit",
    )
    return parser.parse_args()


def import_serial():
    try:
        import serial  # type: ignore
        from serial.tools import list_ports  # type: ignore
    except ImportError:
        print(
            "缺少 pyserial。請先執行：py -m pip install pyserial",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return serial, list_ports


def output_path_for(args: argparse.Namespace) -> Path:
    if args.output is not None:
        return args.output.expanduser().resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(__file__).resolve().parents[2] / "Data" / "TestRecords"
    return output_dir / f"mcu_vision_{args.mode}_{stamp}.csv"


def parse_firmware_sample(line: str) -> list[float | int] | None:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != len(FIRMWARE_FIELDS) or any(part == "" for part in parts):
        return None

    values: list[float | int] = []
    try:
        for index, part in enumerate(parts):
            number = float(part)
            if index in INTEGER_FIELD_INDEXES:
                if not number.is_integer():
                    return None
                values.append(int(number))
            else:
                values.append(number)
    except ValueError:
        return None
    return values


def parse_vision_sample(line: str) -> dict[str, float | int] | None:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != 11 or parts[0] != "V" or any(part == "" for part in parts):
        return None
    try:
        values = [int(part) for part in parts[1:]]
    except ValueError:
        return None
    (
        stm32_time_ms,
        rx_seq,
        pi_time_ms,
        tracking_valid,
        rx_age_ms,
        packet_x_001cm,
        estimate_valid,
        estimated_x_001cm,
        estimated_vx_001cms,
        vision_age_ms,
    ) = values
    return {
        "stm32_time_ms": stm32_time_ms,
        "rx_present": int(pi_time_ms != 0),
        "rx_seq": rx_seq,
        "pi_time_ms": pi_time_ms,
        "tracking_valid": tracking_valid,
        "rx_age_ms": rx_age_ms,
        "packet_x_cm": packet_x_001cm * 0.01,
        "estimate_valid": estimate_valid,
        "estimated_x_cm": estimated_x_001cm * 0.01,
        "estimated_vx_cm_s": estimated_vx_001cms * 0.01,
        "vision_age_ms": vision_age_ms,
    }


def write_event(
    writer: csv.DictWriter,
    started_ns: int,
    record_type: str,
    text: str,
) -> None:
    now_ns = time.time_ns()
    row = {
        "host_iso8601": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "host_unix_ns": now_ns,
        "elapsed_s": f"{(time.perf_counter_ns() - started_ns) / 1e9:.6f}",
        "record_type": record_type,
        "raw_line": text,
    }
    writer.writerow(row)


def send_command(ser, writer: csv.DictWriter, started_ns: int, command: str) -> None:
    write_event(writer, started_ns, "host_command", command)
    ser.write((command + "\r\n").encode("ascii"))
    ser.flush()
    print(f"> {command}", flush=True)


def capture(args: argparse.Namespace, serial_module) -> int:
    output_path = output_path_for(args)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sample_count = 0
    text_count = 0
    bad_count = 0
    previous_rx_ns: int | None = None
    previous_x: float | None = None
    x_changed_ns: int | None = None
    latest_x = 0.0
    latest_vx = 0.0
    latest_age_ms = 0
    latest_tracking_valid = -1
    latest_rx_seq = -1
    max_age_ms = 0
    started_perf_ns = time.perf_counter_ns()
    deadline_ns = (
        started_perf_ns + int(args.duration_s * 1e9) if args.duration_s > 0 else None
    )
    next_report_ns = started_perf_ns + int(max(args.report_s, 0.1) * 1e9)
    next_flush_ns = started_perf_ns + int(max(args.flush_s, 0.05) * 1e9)

    print(f"輸出：{output_path}", flush=True)
    print(f"開啟 {args.port} @ {args.baudrate}", flush=True)

    try:
        with serial_module.Serial(
            args.port,
            args.baudrate,
            timeout=0.10,
            write_timeout=1.0,
        ) as ser, output_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            write_event(writer, started_perf_ns, "capture_start", f"mode={args.mode}")

            if args.firmware_csv != "unchanged":
                send_command(
                    ser,
                    writer,
                    started_perf_ns,
                    f"csv {args.firmware_csv}",
                )

            if args.mode == "ba22":
                send_command(ser, writer, started_perf_ns, "ba 22")
            elif args.mode == "task1":
                send_command(ser, writer, started_perf_ns, "task 1")

            try:
                while deadline_ns is None or time.perf_counter_ns() < deadline_ns:
                    raw = ser.readline()
                    rx_perf_ns = time.perf_counter_ns()
                    if not raw:
                        continue

                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    vision_values = parse_vision_sample(line)
                    values = (
                        None if vision_values is not None else parse_firmware_sample(line)
                    )
                    host_unix_ns = time.time_ns()
                    common = {
                        "host_iso8601": datetime.now()
                        .astimezone()
                        .isoformat(timespec="milliseconds"),
                        "host_unix_ns": host_unix_ns,
                        "elapsed_s": f"{(rx_perf_ns - started_perf_ns) / 1e9:.6f}",
                        "rx_interval_ms": (
                            ""
                            if previous_rx_ns is None
                            else f"{(rx_perf_ns - previous_rx_ns) / 1e6:.3f}"
                        ),
                        "raw_line": line,
                    }
                    previous_rx_ns = rx_perf_ns

                    if (values is None) and (vision_values is None):
                        record_type = "device_text"
                        # A comma-containing malformed telemetry row is distinct from
                        # ordinary command/status text and must remain visible.
                        if "," in line:
                            record_type = "unparsed_csv"
                            bad_count += 1
                        else:
                            text_count += 1
                        writer.writerow({**common, "record_type": record_type})
                    else:
                        if vision_values is not None:
                            firmware = vision_values
                            record_type = "vision_sample"
                            latest_tracking_valid = int(firmware["tracking_valid"])
                            latest_rx_seq = int(firmware["rx_seq"])
                        else:
                            assert values is not None
                            firmware = dict(zip(FIRMWARE_FIELDS, values))
                            record_type = "control_sample"
                        current_x = float(firmware["estimated_x_cm"])
                        if previous_x is None or current_x != previous_x:
                            changed = 1
                            x_changed_ns = rx_perf_ns
                        else:
                            changed = 0
                        x_unchanged_ms = (
                            0.0
                            if x_changed_ns is None
                            else (rx_perf_ns - x_changed_ns) / 1e6
                        )
                        previous_x = current_x
                        latest_x = current_x
                        latest_vx = float(firmware["estimated_vx_cm_s"])
                        latest_age_ms = int(firmware["vision_age_ms"])
                        max_age_ms = max(max_age_ms, latest_age_ms)
                        sample_count += 1
                        writer.writerow(
                            {
                                **common,
                                "record_type": record_type,
                                **firmware,
                                "x_changed": changed,
                                "x_unchanged_ms": f"{x_unchanged_ms:.3f}",
                            }
                        )

                    if rx_perf_ns >= next_flush_ns:
                        stream.flush()
                        next_flush_ns = rx_perf_ns + int(max(args.flush_s, 0.05) * 1e9)
                    if rx_perf_ns >= next_report_ns:
                        held_ms = (
                            0.0
                            if x_changed_ns is None
                            else (rx_perf_ns - x_changed_ns) / 1e6
                        )
                        print(
                            f"samples={sample_count} x={latest_x:+.2f} cm "
                            f"vx={latest_vx:+.2f} cm/s age={latest_age_ms} ms "
                            f"x_hold={held_ms:.0f} ms valid={latest_tracking_valid} "
                            f"seq={latest_rx_seq} bad={bad_count}",
                            flush=True,
                        )
                        next_report_ns = rx_perf_ns + int(max(args.report_s, 0.1) * 1e9)
            except KeyboardInterrupt:
                print("收到 Ctrl+C，正在安全收尾……", flush=True)
            finally:
                if args.mode == "task1":
                    try:
                        send_command(ser, writer, started_perf_ns, "task stop")
                    except (serial_module.SerialException, serial_module.SerialTimeoutException):
                        write_event(
                            writer,
                            started_perf_ns,
                            "host_error",
                            "failed_to_send_task_stop",
                        )
                write_event(writer, started_perf_ns, "capture_stop", "normal_exit")
                stream.flush()
    except serial_module.SerialException as exc:
        print(f"串口錯誤：{exc}", file=sys.stderr)
        print("請確認 COM 號正確，並關閉 VOFA、串口助手等佔用程式。", file=sys.stderr)
        return 2

    print(
        f"完成：samples={sample_count}, device_text={text_count}, "
        f"unparsed_csv={bad_count}, max_vision_age={max_age_ms} ms",
        flush=True,
    )
    print(f"CSV：{output_path}", flush=True)
    return 0


def main() -> int:
    args = parse_args()
    if args.duration_s < 0:
        print("--duration-s 不能小於 0", file=sys.stderr)
        return 2

    serial_module, list_ports = import_serial()
    if args.list_ports:
        ports = list(list_ports.comports())
        if not ports:
            print("未找到串口。")
            return 0
        for port in ports:
            print(f"{port.device}\t{port.description}\t{port.hwid}")
        return 0

    return capture(args, serial_module)


if __name__ == "__main__":
    raise SystemExit(main())
