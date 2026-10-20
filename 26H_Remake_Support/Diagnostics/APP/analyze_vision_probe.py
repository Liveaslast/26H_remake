#!/usr/bin/env python3
"""Analyze vision probe CSV quality for motion and velocity estimation."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze visual measurement, finite-difference velocity and Kalman velocity quality."
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--max-dt-ms", type=float, default=80.0)
    parser.add_argument("--min-speed-cm-s", type=float, default=1.0)
    parser.add_argument(
        "--control-period-ms",
        type=float,
        default=25.0,
        help="outer-loop period used to count visual update gaps",
    )
    parser.add_argument(
        "--reversal-min-speed-cm-s",
        type=float,
        default=2.0,
        help="minimum speed on both sides of a sign change to count a reversal",
    )
    parser.add_argument(
        "--top-events",
        type=int,
        default=5,
        help="number of largest acceleration/reversal events to print",
    )
    parser.add_argument(
        "--velocity-fit-compare",
        action="store_true",
        help="compare causal finite difference and multi-point slopes on per-frame sent_x",
    )
    parser.add_argument(
        "--velocity-fit-windows",
        nargs="+",
        type=int,
        default=[2, 3, 5],
        metavar="N",
        help="numbers of distinct vision frames per slope fit (default: 2 3 5)",
    )
    parser.add_argument(
        "--velocity-fit-end-s",
        type=float,
        help="compare only the first N seconds from the first probe frame",
    )
    return parser.parse_args()


def number(row: dict[str, str], key: str) -> float | None:
    raw = row.get(key, "")
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def mean(values: list[float]) -> float:
    return statistics.mean(values) if values else float("nan")


def stdev(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) >= 2 else 0.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def rms(values: list[float]) -> float:
    if not values:
        return float("nan")
    return math.sqrt(sum(value * value for value in values) / len(values))


def finite_difference(
    samples: list[dict[str, float | bool | str]],
    key: str,
    *,
    valid_key: str,
    max_dt_seconds: float,
) -> list[dict[str, float]]:
    values: list[dict[str, float]] = []
    previous: dict[str, float | bool | str] | None = None
    for sample in samples:
        value = float(sample[key])
        if not bool(sample[valid_key]) or not math.isfinite(value):
            continue
        if previous is not None:
            previous_value = float(previous[key])
            dt = float(sample["t"]) - float(previous["t"])
            if (
                0.0 < dt <= max_dt_seconds
                and math.isfinite(previous_value)
            ):
                values.append(
                    {
                        "t": float(sample["t"]),
                        "dt": dt,
                        "value": (value - previous_value) / dt,
                        "x0": previous_value,
                        "x1": value,
                    }
                )
        previous = sample
    return values


def derivative_from_series(
    series: list[dict[str, float]],
    *,
    max_dt_seconds: float,
) -> list[dict[str, float]]:
    values: list[dict[str, float]] = []
    for previous, current in zip(series, series[1:]):
        dt = current["t"] - previous["t"]
        if 0.0 < dt <= max_dt_seconds:
            values.append(
                {
                    "t": current["t"],
                    "dt": dt,
                    "value": (current["value"] - previous["value"]) / dt,
                    "v0": previous["value"],
                    "v1": current["value"],
                }
            )
    return values


def reversal_events(
    velocity: list[dict[str, float]],
    *,
    min_speed: float,
) -> list[dict[str, float]]:
    events: list[dict[str, float]] = []
    previous: dict[str, float] | None = None
    for item in velocity:
        value = item["value"]
        if abs(value) < min_speed:
            continue
        if (
            previous is not None
            and previous["value"] * value < 0.0
            and abs(previous["value"]) >= min_speed
        ):
            events.append(
                {
                    "t": item["t"],
                    "dt": item["t"] - previous["t"],
                    "v0": previous["value"],
                    "v1": value,
                }
            )
        previous = item
    return events


def summarize_abs(values: list[float]) -> str:
    absolute = [abs(value) for value in values]
    return (
        f"{rms(values):.2f} / {stdev(values):.2f} / "
        f"{percentile(absolute, 0.95):.2f} / "
        f"{max(absolute) if absolute else float('nan'):.2f}"
    )


def print_top_events(name: str, events: list[dict[str, float]], *, count: int) -> None:
    if count <= 0 or not events:
        return
    print(f"{name}:")
    for event in events[:count]:
        parts = [f"t={event['t']:.3f}s"]
        if "value" in event:
            parts.append(f"value={event['value']:.2f}")
        if "v0" in event and "v1" in event:
            parts.append(f"v={event['v0']:.2f}->{event['v1']:.2f}")
        if "dt" in event:
            parts.append(f"dt={event['dt'] * 1000.0:.1f}ms")
        print("  " + " ".join(parts))


def print_velocity_fit_comparison(
    samples: list[dict[str, float | bool | str]],
    windows: list[int],
    max_dt_seconds: float,
    end_seconds: float | None,
) -> None:
    if any(window < 2 or window > 20 for window in windows):
        raise SystemExit("--velocity-fit-windows values must be within 2..20")
    windows = sorted(set(windows))
    if end_seconds is not None:
        if not math.isfinite(end_seconds) or end_seconds <= 0.0:
            raise SystemExit("--velocity-fit-end-s must be positive")
        first_t = float(samples[0]["t"])
        samples = [sample for sample in samples if float(sample["t"]) - first_t <= end_seconds]
    history: list[tuple[float, float]] = []
    records: list[tuple[int, float, float, dict[str, float]]] = []
    for index, sample in enumerate(samples):
        t = float(sample["t"])
        x = float(sample["sent_x"])
        if not bool(sample["sent_valid"]) or not math.isfinite(x):
            history.clear()
            continue
        if history and not 0.0 < t - history[-1][0] <= max_dt_seconds:
            history.clear()
        history.append((t, x))
        history = history[-max(windows):]
        if len(history) < max(windows):
            continue

        velocities: dict[str, float] = {}
        for window in windows:
            points = history[-window:]
            t0 = points[0][0]
            elapsed = [point[0] - t0 for point in points]
            t_mean = mean(elapsed)
            x_mean = mean([point[1] for point in points])
            denominator = sum((value - t_mean) ** 2 for value in elapsed)
            if denominator <= 0.0:
                continue
            velocities[f"slope_{window}"] = sum(
                (elapsed[i] - t_mean) * (points[i][1] - x_mean)
                for i in range(window)
            ) / denominator
        kalman_v = float(sample["kalman_v"])
        if math.isfinite(kalman_v):
            velocities["pi_kalman"] = kalman_v
        if all(f"slope_{window}" in velocities for window in windows):
            records.append((index, t, x, velocities))

    if len(records) < 3:
        print("velocity_fit_compare: not enough consecutive valid frame measurements")
        return

    names = [f"slope_{window}" for window in windows]
    kalman_values = [record[3].get("pi_kalman") for record in records]
    if (all(value is not None for value in kalman_values)
            and max(kalman_values) - min(kalman_values) > 0.01):
        names.append("pi_kalman")
    print(f"velocity_fit_compare: {len(records)} eligible frames; source=sent_x_cm, clock=frame capture t")
    print("  method       next_frame_MAE_cm  v_step_p95_cm_s  compared_steps")
    for name in names:
        errors: list[float] = []
        changes: list[float] = []
        for previous, current in zip(records, records[1:]):
            previous_index, previous_t, previous_x, previous_v = previous
            current_index, current_t, current_x, current_v = current
            dt = current_t - previous_t
            if current_index != previous_index + 1 or not 0.0 < dt <= max_dt_seconds:
                continue
            errors.append(abs(current_x - (previous_x + previous_v[name] * dt)))
            changes.append(abs(current_v[name] - previous_v[name]))
        print(
            f"  {name:<12s} {mean(errors):>17.4f} "
            f"{percentile(changes, 0.95):>16.2f} {len(errors):>15d}"
        )
    if "pi_kalman" not in names:
        print("  pi_kalman omitted: no changing velocity output in this interval.")
    print("  No trajectory ground truth: prediction error and velocity steps are diagnostics, not accuracy.")


def main() -> int:
    args = parse_args()
    with args.csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("CSV is empty")

    samples: list[dict[str, float | bool | str]] = []
    for row in rows:
        t = number(row, "t")
        measured = number(row, "measurement_x_cm")
        if measured is None:
            measured = number(row, "raw_x_cm")
        kalman_x = number(row, "kalman_x_cm")
        if kalman_x is None:
            kalman_x = number(row, "raw_x_cm")
        kalman_v = number(row, "kalman_vx_cm_s")
        if kalman_v is None:
            kalman_v = number(row, "raw_vx_cm_s")
        sent_x = number(row, "sent_x_cm")
        if t is None:
            continue
        samples.append(
            {
                "t": t,
                "measurement_x": measured if measured is not None else float("nan"),
                "kalman_x": kalman_x if kalman_x is not None else float("nan"),
                "kalman_v": kalman_v if kalman_v is not None else float("nan"),
                "sent_x": sent_x if sent_x is not None else float("nan"),
                "measurement_valid": row.get("measurement_valid") == "1",
                "tracking_valid": row.get("tracking_valid") == "1",
                "sent_valid": row.get("sent_valid") == "1",
                "source": row.get("source", ""),
            }
        )

    if len(samples) < 2:
        raise SystemExit("Not enough samples")

    duration = float(samples[-1]["t"]) - float(samples[0]["t"])
    total = len(samples)
    valid = [sample for sample in samples if bool(sample["measurement_valid"])]
    tracking_valid = [sample for sample in samples if bool(sample["tracking_valid"])]

    max_dt_seconds = args.max_dt_ms / 1000.0
    measurement_v_series = finite_difference(
        samples,
        "measurement_x",
        valid_key="measurement_valid",
        max_dt_seconds=max_dt_seconds,
    )
    kalman_dx_v_series = finite_difference(
        samples,
        "kalman_x",
        valid_key="tracking_valid",
        max_dt_seconds=max_dt_seconds,
    )
    sent_dx_v_series = finite_difference(
        samples,
        "sent_x",
        valid_key="sent_valid",
        max_dt_seconds=max_dt_seconds,
    )
    measurement_a_series = derivative_from_series(
        measurement_v_series,
        max_dt_seconds=max_dt_seconds,
    )
    kalman_dx_a_series = derivative_from_series(
        kalman_dx_v_series,
        max_dt_seconds=max_dt_seconds,
    )
    measurement_reversals = reversal_events(
        measurement_v_series,
        min_speed=args.reversal_min_speed_cm_s,
    )
    sent_reversals = reversal_events(
        sent_dx_v_series,
        min_speed=args.reversal_min_speed_cm_s,
    )
    dts = [item["dt"] for item in measurement_v_series]
    measurement_v = [item["value"] for item in measurement_v_series]
    kalman_dx_v = [item["value"] for item in kalman_dx_v_series]
    sent_dx_v = [item["value"] for item in sent_dx_v_series]
    measurement_a = [item["value"] for item in measurement_a_series]
    kalman_dx_a = [item["value"] for item in kalman_dx_a_series]

    kalman_v_values = [
        float(sample["kalman_v"])
        for sample in samples
        if math.isfinite(float(sample["kalman_v"])) and bool(sample["tracking_valid"])
    ]
    measurement_x_values = [
        float(sample["measurement_x"])
        for sample in valid
        if math.isfinite(float(sample["measurement_x"]))
    ]
    kalman_x_values = [
        float(sample["kalman_x"])
        for sample in tracking_valid
        if math.isfinite(float(sample["kalman_x"]))
    ]
    sent_x_values = [
        float(sample["sent_x"])
        for sample in samples
        if bool(sample["sent_valid"]) and math.isfinite(float(sample["sent_x"]))
    ]
    sent_minus_measurement = [
        float(sample["sent_x"]) - float(sample["measurement_x"])
        for sample in samples
        if (
            bool(sample["sent_valid"])
            and bool(sample["measurement_valid"])
            and math.isfinite(float(sample["sent_x"]))
            and math.isfinite(float(sample["measurement_x"]))
        )
    ]
    kalman_minus_measurement = [
        float(sample["kalman_x"]) - float(sample["measurement_x"])
        for sample in samples
        if (
            bool(sample["tracking_valid"])
            and bool(sample["measurement_valid"])
            and math.isfinite(float(sample["kalman_x"]))
            and math.isfinite(float(sample["measurement_x"]))
        )
    ]
    moving_fd = [value for value in measurement_v if abs(value) >= args.min_speed_cm_s]
    moving_kalman = [value for value in kalman_v_values if abs(value) >= args.min_speed_cm_s]
    control_gap_threshold = args.control_period_ms / 1000.0
    control_period_gaps = [dt for dt in dts if dt > control_gap_threshold]
    invalid_runs: list[float] = []
    run_started: float | None = None
    last_t = float(samples[0]["t"])
    for sample in samples:
        t = float(sample["t"])
        if not bool(sample["measurement_valid"]):
            if run_started is None:
                run_started = t
        elif run_started is not None:
            invalid_runs.append(t - run_started)
            run_started = None
        last_t = t
    if run_started is not None:
        invalid_runs.append(last_t - run_started)

    print(f"file: {args.csv_path}")
    print(f"duration_s: {duration:.3f}")
    print(f"sample_count: {total}")
    print(f"loop_hz_from_csv: {total / duration if duration > 0 else float('nan'):.2f}")
    print(f"measurement_valid_rate: {len(valid) / total * 100:.2f}%")
    print(f"tracking_valid_rate: {len(tracking_valid) / total * 100:.2f}%")
    print(f"valid_measurement_hz: {len(valid) / duration if duration > 0 else float('nan'):.2f}")
    print(f"dt_ms mean/p95/max: {mean(dts) * 1000:.2f} / {percentile(dts, 0.95) * 1000:.2f} / {max(dts) * 1000 if dts else float('nan'):.2f}")
    print(f"measurement_x_cm std/peak_to_peak: {stdev(measurement_x_values):.4f} / {(max(measurement_x_values) - min(measurement_x_values)) if measurement_x_values else float('nan'):.4f}")
    print(f"kalman_x_cm std/peak_to_peak: {stdev(kalman_x_values):.4f} / {(max(kalman_x_values) - min(kalman_x_values)) if kalman_x_values else float('nan'):.4f}")
    print(f"sent_x_cm std/peak_to_peak: {stdev(sent_x_values):.4f} / {(max(sent_x_values) - min(sent_x_values)) if sent_x_values else float('nan'):.4f}")
    print(f"sent_minus_measurement_cm mean/p95abs/maxabs: {mean(sent_minus_measurement):.4f} / {percentile([abs(v) for v in sent_minus_measurement], 0.95):.4f} / {max([abs(v) for v in sent_minus_measurement]) if sent_minus_measurement else float('nan'):.4f}")
    print(f"kalman_minus_measurement_cm mean/p95abs/maxabs: {mean(kalman_minus_measurement):.4f} / {percentile([abs(v) for v in kalman_minus_measurement], 0.95):.4f} / {max([abs(v) for v in kalman_minus_measurement]) if kalman_minus_measurement else float('nan'):.4f}")
    print(f"finite_diff_v_cm_s rms/std/p95abs: {rms(measurement_v):.2f} / {stdev(measurement_v):.2f} / {percentile([abs(v) for v in measurement_v], 0.95):.2f}")
    print(f"kalman_dx_v_cm_s rms/std/p95abs: {rms(kalman_dx_v):.2f} / {stdev(kalman_dx_v):.2f} / {percentile([abs(v) for v in kalman_dx_v], 0.95):.2f}")
    print(f"sent_dx_v_cm_s rms/std/p95abs: {rms(sent_dx_v):.2f} / {stdev(sent_dx_v):.2f} / {percentile([abs(v) for v in sent_dx_v], 0.95):.2f}")
    print(f"kalman_v_cm_s rms/std/p95abs: {rms(kalman_v_values):.2f} / {stdev(kalman_v_values):.2f} / {percentile([abs(v) for v in kalman_v_values], 0.95):.2f}")
    print(f"finite_diff_a_cm_s2 rms/std/p95abs/maxabs: {summarize_abs(measurement_a)}")
    print(f"kalman_dx_a_cm_s2 rms/std/p95abs/maxabs: {summarize_abs(kalman_dx_a)}")
    print(f"finite_diff_speed_abs_cm_s p50/p95/max: {percentile([abs(v) for v in measurement_v], 0.50):.2f} / {percentile([abs(v) for v in measurement_v], 0.95):.2f} / {max([abs(v) for v in measurement_v]) if measurement_v else float('nan'):.2f}")
    print(f"control_period_gaps>{args.control_period_ms:.1f}ms count/max_ms: {len(control_period_gaps)} / {max(control_period_gaps) * 1000 if control_period_gaps else 0.0:.1f}")
    print(f"measurement_reversals count: {len(measurement_reversals)}")
    print(f"sent_reversals count: {len(sent_reversals)}")
    print(f"moving_fd_samples: {len(moving_fd)}")
    print(f"moving_kalman_samples: {len(moving_kalman)}")
    print(f"invalid_runs count/max_ms: {len(invalid_runs)} / {max(invalid_runs) * 1000 if invalid_runs else 0.0:.1f}")
    top_accel = sorted(
        measurement_a_series,
        key=lambda item: abs(item["value"]),
        reverse=True,
    )
    print_top_events(
        "top_finite_diff_accel_events_cm_s2",
        top_accel,
        count=args.top_events,
    )
    print_top_events(
        "measurement_reversal_events",
        measurement_reversals,
        count=args.top_events,
    )
    if args.velocity_fit_compare:
        print_velocity_fit_comparison(
            samples, args.velocity_fit_windows, max_dt_seconds,
            args.velocity_fit_end_s,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
