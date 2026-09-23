#!/usr/bin/env python3
"""Check whether two serial ports can exchange data reliably.

Example:
    python serial_duplex_check.py --port-a COM22 --port-b COM5
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
import queue
import re
import threading
import time

try:
    import serial
except ImportError as exc:  # pragma: no cover - depends on local env
    raise SystemExit(
        "Missing pyserial. Install it with: python -m pip install pyserial"
    ) from exc


LINE_RE = re.compile(
    rb"^SRC=(?P<src>[AB]);SEQ=(?P<seq>\d+);T=(?P<sent_ns>\d+);PAYLOAD=(?P<payload>[0-9A-F]+)$"
)


@dataclass
class PortStats:
    sent: int = 0
    received: int = 0
    decoded_ok: int = 0
    decoded_bad: int = 0
    unexpected_src: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    read_errors: int = 0
    write_errors: int = 0
    received_sequences: set[int] = field(default_factory=set)
    last_sequence: int | None = None
    latency_ms: list[float] = field(default_factory=list)
    bad_samples: list[bytes] = field(default_factory=list)


def build_payload(seq: int, size: int) -> str:
    seed = f"{seq:08X}"
    repeated = (seed * ((size // len(seed)) + 1))[:size]
    return repeated


def make_line(src: str, seq: int, payload_size: int) -> bytes:
    return (
        f"SRC={src};SEQ={seq};T={time.monotonic_ns()};"
        f"PAYLOAD={build_payload(seq, payload_size)}\n"
    ).encode("ascii")


def writer_loop(
    port,
    src: str,
    stats: PortStats,
    stop_event: threading.Event,
    interval: float,
    payload_size: int,
) -> None:
    seq = 0
    while not stop_event.is_set():
        try:
            port.write(make_line(src, seq, payload_size))
            stats.sent += 1
            seq += 1
        except serial.SerialException:
            stats.write_errors += 1
        stop_event.wait(interval)


def reader_loop(
    port,
    expected_src: str,
    stats: PortStats,
    stop_event: threading.Event,
    events: queue.Queue[str],
) -> None:
    while not stop_event.is_set():
        try:
            line = port.readline()
        except serial.SerialException as exc:
            stats.read_errors += 1
            events.put(f"{port.port}: read error: {exc}")
            stop_event.wait(0.05)
            continue

        if not line:
            continue
        line = line.rstrip(b"\r\n")
        stats.received += 1
        match = LINE_RE.match(line)
        if match is None:
            stats.decoded_bad += 1
            if len(stats.bad_samples) < 5:
                stats.bad_samples.append(line[:160])
            continue

        src = match.group("src").decode("ascii")
        seq = int(match.group("seq"))
        sent_ns = int(match.group("sent_ns"))
        if src != expected_src:
            stats.unexpected_src += 1
            continue

        if seq in stats.received_sequences:
            stats.duplicates += 1
        stats.received_sequences.add(seq)
        if stats.last_sequence is not None and seq <= stats.last_sequence:
            stats.out_of_order += 1
        stats.last_sequence = seq
        stats.decoded_ok += 1
        stats.latency_ms.append((time.monotonic_ns() - sent_ns) / 1_000_000.0)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[index]


def summarize(name: str, tx_stats: PortStats, rx_stats: PortStats) -> str:
    missing = max(0, tx_stats.sent - rx_stats.decoded_ok)
    p50 = percentile(rx_stats.latency_ms, 0.50)
    p95 = percentile(rx_stats.latency_ms, 0.95)
    latency = (
        "latency=none"
        if p50 is None or p95 is None
        else f"latency_p50={p50:.1f}ms latency_p95={p95:.1f}ms"
    )
    return (
        f"{name}: sent={tx_stats.sent} ok={rx_stats.decoded_ok} "
        f"missing~={missing} raw_rx={rx_stats.received} "
        f"bad={rx_stats.decoded_bad} unexpected_src={rx_stats.unexpected_src} "
        f"dup={rx_stats.duplicates} out_of_order={rx_stats.out_of_order} "
        f"read_err={rx_stats.read_errors} write_err={tx_stats.write_errors} "
        f"{latency}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bidirectional serial link checker for two COM ports.",
    )
    parser.add_argument("--port-a", default="COM22")
    parser.add_argument("--port-b", default="COM5")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--interval-ms", type=float, default=50.0)
    parser.add_argument("--payload-size", type=int, default=32)
    parser.add_argument("--timeout-ms", type=float, default=100.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.baudrate <= 0:
        raise SystemExit("--baudrate must be positive")
    if args.duration <= 0:
        raise SystemExit("--duration must be positive")
    if args.interval_ms <= 0:
        raise SystemExit("--interval-ms must be positive")
    if args.payload_size < 1:
        raise SystemExit("--payload-size must be at least 1")

    timeout = args.timeout_ms / 1000.0
    interval = args.interval_ms / 1000.0
    stop_event = threading.Event()
    events: queue.Queue[str] = queue.Queue()
    stats: dict[str, PortStats] = defaultdict(PortStats)

    with serial.Serial(args.port_a, args.baudrate, timeout=timeout) as port_a, serial.Serial(
        args.port_b,
        args.baudrate,
        timeout=timeout,
    ) as port_b:
        port_a.reset_input_buffer()
        port_b.reset_input_buffer()
        port_a.reset_output_buffer()
        port_b.reset_output_buffer()

        print(
            f"Opened {args.port_a} <-> {args.port_b} @ {args.baudrate}; "
            f"duration={args.duration}s interval={args.interval_ms}ms",
            flush=True,
        )
        threads = [
            threading.Thread(
                target=writer_loop,
                args=(port_a, "A", stats["a_tx"], stop_event, interval, args.payload_size),
                daemon=True,
            ),
            threading.Thread(
                target=writer_loop,
                args=(port_b, "B", stats["b_tx"], stop_event, interval, args.payload_size),
                daemon=True,
            ),
            threading.Thread(
                target=reader_loop,
                args=(port_a, "B", stats["a_rx"], stop_event, events),
                daemon=True,
            ),
            threading.Thread(
                target=reader_loop,
                args=(port_b, "A", stats["b_rx"], stop_event, events),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()

        started = time.monotonic()
        next_report = started + 1.0
        try:
            while time.monotonic() - started < args.duration:
                now = time.monotonic()
                while True:
                    try:
                        print(events.get_nowait(), flush=True)
                    except queue.Empty:
                        break
                if now >= next_report:
                    print(
                        summarize(f"{args.port_a}-> {args.port_b}", stats["a_tx"], stats["b_rx"]),
                        flush=True,
                    )
                    print(
                        summarize(f"{args.port_b}-> {args.port_a}", stats["b_tx"], stats["a_rx"]),
                        flush=True,
                    )
                    next_report = now + 1.0
                time.sleep(0.05)
        except KeyboardInterrupt:
            print("Interrupted, stopping...", flush=True)
        finally:
            stop_event.set()
            for thread in threads:
                thread.join(timeout=1.0)

    print("Final:")
    print(summarize(f"{args.port_a}-> {args.port_b}", stats["a_tx"], stats["b_rx"]))
    print(summarize(f"{args.port_b}-> {args.port_a}", stats["b_tx"], stats["a_rx"]))
    for name in ("a_rx", "b_rx"):
        if stats[name].bad_samples:
            print(f"{name} bad samples:")
            for sample in stats[name].bad_samples:
                print(f"  {sample!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
