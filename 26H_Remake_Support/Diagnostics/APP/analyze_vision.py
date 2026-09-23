#!/usr/bin/env python3
"""Analyze synchronized MCU debug CSV and Raspberry Pi vision-probe CSV."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path


def number(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def percentile(values: list[float], p: float) -> float | None:
    values = sorted(v for v in values if math.isfinite(v))
    if not values:
        return None
    pos = (len(values) - 1) * p / 100.0
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def stats(values: list[float]) -> str:
    values = [v for v in values if math.isfinite(v)]
    if not values:
        return "n/a"
    return (
        f"mean={statistics.fmean(values):.3f}, median={percentile(values, 50):.3f}, "
        f"p95={percentile(values, 95):.3f}, p99={percentile(values, 99):.3f}, "
        f"max={max(values):.3f}"
    )


def delta_u32(current: float, previous: float) -> float:
    delta = current - previous
    return delta if delta >= 0 else delta + 2**32


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def newest(folder: Path, pattern: str) -> Path | None:
    paths = list(folder.glob(pattern))
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def analyze_mcu(path: Path) -> tuple[float, float] | None:
    rows = [r for r in read_csv(path) if r.get("record_type") == "vision_sample"]
    print(f"MCU_FILE={path}")
    print(f"MCU_VISION_ROWS={len(rows)}")
    if len(rows) < 2:
        print("MCU_RESULT=insufficient rows")
        return None

    stm = [number(r.get("stm32_time_ms")) for r in rows]
    stm = [v for v in stm if v is not None]
    stm_dt = [delta_u32(b, a) for a, b in zip(stm, stm[1:])]
    duration_s = sum(stm_dt) / 1000.0
    rate_hz = (len(stm) - 1) / duration_s if duration_s else float("nan")
    missing_slots = sum(max(0, round(dt / 5.0) - 1) for dt in stm_dt)
    off_period = sum(abs(dt - 5.0) > 0.51 for dt in stm_dt)

    host_dt = [number(r.get("rx_interval_ms")) for r in rows]
    host_dt = [v for v in host_dt if v is not None]
    tracking = [number(r.get("tracking_valid")) for r in rows]
    estimate = [number(r.get("estimate_valid")) for r in rows]
    rx_age = [number(r.get("rx_age_ms")) for r in rows]
    vision_age = [number(r.get("vision_age_ms")) for r in rows]
    packet_x = [number(r.get("packet_x_cm")) for r in rows]

    tracking_values = [v for v in tracking if v is not None]
    estimate_values = [v for v in estimate if v is not None]
    print(f"MCU_DURATION_S={duration_s:.3f}")
    print(f"DEBUG_RATE_HZ={rate_hz:.3f}")
    print(f"DEBUG_STM32_DT_MS={stats(stm_dt)}")
    print(f"HOST_RX_DT_MS={stats(host_dt)}")
    print(f"DEBUG_MISSING_5MS_SLOTS={missing_slots}")
    print(f"DEBUG_NON_5MS_INTERVALS={off_period}/{len(stm_dt)}")
    if tracking_values:
        print(f"TRACKING_VALID_RATE={100.0 * sum(tracking_values) / len(tracking_values):.2f}%")
    if estimate_values:
        print(f"ESTIMATE_VALID_RATE={100.0 * sum(estimate_values) / len(estimate_values):.2f}%")
    print(f"RX_AGE_MS={stats([v for v in rx_age if v is not None])}")
    print(f"VISION_AGE_MS={stats([v for v in vision_age if v is not None])}")

    seq_events: list[tuple[float, float, float]] = []
    previous_seq = previous_pi = previous_stm = None
    for row in rows:
        seq = number(row.get("rx_seq"))
        pi_ms = number(row.get("pi_time_ms"))
        stm_ms = number(row.get("stm32_time_ms"))
        if seq is None or pi_ms is None or stm_ms is None:
            continue
        if previous_seq is not None and seq != previous_seq:
            seq_events.append(
                (
                    delta_u32(seq, previous_seq),
                    delta_u32(pi_ms, previous_pi),
                    delta_u32(stm_ms, previous_stm),
                )
            )
        if seq != previous_seq:
            previous_seq, previous_pi, previous_stm = seq, pi_ms, stm_ms

    if seq_events:
        seq_steps = [x[0] for x in seq_events]
        pi_steps = [x[1] for x in seq_events]
        stm_steps = [x[2] for x in seq_events]
        pi_duration = sum(pi_steps) / 1000.0
        observed_duration = sum(stm_steps) / 1000.0
        print(f"PI_PACKET_EVENTS={len(seq_events) + 1}")
        print(f"OBSERVED_NEW_PACKET_RATE_HZ={len(seq_events) / observed_duration:.3f}")
        print(f"PI_SEQ_ADVANCE_RATE_HZ={sum(seq_steps) / pi_duration:.3f}")
        print(f"PI_PACKET_DT_MS={stats(pi_steps)}")
        print(f"MCU_PACKET_ARRIVAL_DT_MS={stats(stm_steps)}")
        print(f"PI_SEQUENCE_GAPS={sum(max(0, round(v) - 1) for v in seq_steps)}")

    unique_packets = []
    previous_seq = None
    for row in rows:
        seq = number(row.get("rx_seq"))
        if seq is not None and seq != previous_seq:
            unique_packets.append(row)
            previous_seq = seq
    injected_zero_invalid = [
        r
        for r in unique_packets
        if number(r.get("tracking_valid")) == 0
        and abs(number(r.get("packet_x_cm")) or 0.0) < 0.005
    ]
    if unique_packets:
        print(f"OBSERVED_UNIQUE_PACKETS={len(unique_packets)}")
        print(
            "ZERO_INVALID_PACKETS="
            f"{len(injected_zero_invalid)} "
            f"({100.0 * len(injected_zero_invalid) / len(unique_packets):.2f}%)"
        )

    valid_x = [v for v in packet_x if v is not None]
    changed_dt: list[float] = []
    jumps: list[float] = []
    previous_x = previous_x_stm = None
    for row in rows:
        x = number(row.get("packet_x_cm"))
        now = number(row.get("stm32_time_ms"))
        if x is None or now is None:
            continue
        if previous_x is not None and x != previous_x:
            changed_dt.append(delta_u32(now, previous_x_stm))
            jumps.append(abs(x - previous_x))
        if x != previous_x:
            previous_x, previous_x_stm = x, now
    if valid_x:
        print(f"PACKET_X_RANGE_CM={min(valid_x):.3f}..{max(valid_x):.3f}")
        print(f"PACKET_X_CHANGE_EVENTS={len(changed_dt)}")
        print(f"PACKET_X_CHANGE_DT_MS={stats(changed_dt)}")
        print(f"PACKET_X_JUMP_CM={stats(jumps)}")
    pi_times = [number(r.get("pi_time_ms")) for r in rows]
    pi_times = [v for v in pi_times if v is not None]
    return (min(pi_times), max(pi_times)) if pi_times else None


def longest_run(rows: list[dict[str, str]], field: str, wanted: int) -> float:
    longest = start = previous = 0.0
    active = False
    for row in rows:
        now = number(row.get("result_ready_t")) or number(row.get("t"))
        value = number(row.get(field))
        if now is None or value is None:
            continue
        if int(value) == wanted:
            if not active:
                start = now
                active = True
            previous = now
            longest = max(longest, previous - start)
        else:
            active = False
    return longest


def analyze_probe(path: Path, pi_window_ms: tuple[float, float] | None = None) -> None:
    rows = read_csv(path)
    print(f"PROBE_FILE={path}")
    print(f"PROBE_ROWS={len(rows)}")
    if len(rows) < 2:
        print("PROBE_RESULT=insufficient rows")
        return

    if pi_window_ms:
        lo, hi = pi_window_ms
        aligned = []
        for row in rows:
            ready = number(row.get("result_ready_t"))
            if ready is not None and lo <= ready * 1000.0 <= hi:
                aligned.append(row)
        if aligned:
            rows = aligned
            print(f"PROBE_ALIGNED_PI_WINDOW_MS={lo:.0f}..{hi:.0f}")
            print(f"PROBE_ALIGNED_ROWS={len(rows)}")

    times = [number(r.get("t")) for r in rows]
    seqs = [number(r.get("frame_seq")) for r in rows]
    pairs = [(t, s) for t, s in zip(times, seqs) if t is not None and s is not None]
    if len(pairs) >= 2:
        duration = pairs[-1][0] - pairs[0][0]
        seq_delta = pairs[-1][1] - pairs[0][1]
        print(f"PROCESSED_DURATION_S={duration:.3f}")
        print(f"PROCESSED_FRAME_RATE_HZ={seq_delta / duration:.3f}")

    inference = [number(r.get("inference_ms")) for r in rows]
    inference = [v for v in inference if v is not None]
    inferred = [v for v in inference if v > 0]
    print(f"INFERENCE_COVERAGE={100.0 * len(inferred) / len(rows):.2f}%")
    print(f"INFERENCE_MS={stats(inferred)}")
    for field in ("refinement_ms", "processing_ms", "capture_to_log_ms"):
        values = [number(r.get(field)) for r in rows]
        print(f"{field.upper()}={stats([v for v in values if v is not None])}")
    for field in ("measurement_valid", "tracking_valid", "sent_valid"):
        values = [number(r.get(field)) for r in rows]
        values = [v for v in values if v is not None]
        if values:
            print(f"{field.upper()}_RATE={100.0 * sum(values) / len(values):.2f}%")
            print(f"{field.upper()}_LONGEST_ZERO_RUN_MS={1000.0 * longest_run(rows, field, 0):.3f}")

    sent_x = [number(r.get("sent_x_cm")) for r in rows]
    sent_x = [v for v in sent_x if v is not None]
    raw_x = [number(r.get("raw_x_cm")) for r in rows]
    raw_x = [v for v in raw_x if v is not None]
    if sent_x:
        print(f"PROBE_SENT_X_RANGE_CM={min(sent_x):.3f}..{max(sent_x):.3f}")
    if raw_x:
        print(f"PROBE_RAW_X_RANGE_CM={min(raw_x):.3f}..{max(raw_x):.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcu", type=Path)
    parser.add_argument("--probe", type=Path)
    parser.add_argument(
        "--folder",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "Data" / "TestRecords",
    )
    args = parser.parse_args()

    mcu = args.mcu or newest(args.folder, "mcu_vision*.csv")
    probe = args.probe or newest(args.folder, "vision_probe*.csv")
    pi_window = None
    if mcu:
        pi_window = analyze_mcu(mcu)
    else:
        print("MCU_FILE=missing")
    if probe:
        analyze_probe(probe, pi_window)
    else:
        print("PROBE_FILE=missing")
        print("PROBE_LIMIT=processed camera FPS and per-frame inference coverage cannot be determined")


if __name__ == "__main__":
    main()
