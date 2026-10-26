import argparse
import csv
import math
from pathlib import Path


def load_rows(path):
    rows = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                parsed = {}
                for key, value in row.items():
                    parsed[key] = value if key == "phase" else float(value)
                rows.append(parsed)
            except ValueError:
                continue
    return rows


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else float("nan")


def std(values):
    values = list(values)
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(mean((v - m) * (v - m) for v in values))


def first_crossing(rows, target, direction):
    for row in rows:
        x = row["ab_x"]
        if direction > 0 and x >= target:
            return row
        if direction < 0 and x <= target:
            return row
    return None


def segment_between(rows, start_x, end_x, direction):
    if direction > 0:
        return [r for r in rows if start_x <= r["ab_x"] <= end_x]
    return [r for r in rows if end_x <= r["ab_x"] <= start_x]


def row_at_or_after(rows, t_s):
    for row in rows:
        if row["t_s"] >= t_s:
            return row
    return None


def row_at_crossing(rows, x_value, direction):
    return first_crossing(rows, x_value, direction)


def fmt_row(row):
    if row is None:
        return "NA"
    seq = ""
    if row.get("seq_stage", 0.0) > 0.0:
        seq = f" seq={int(row.get('seq_stage', 0.0))}"
    return (
        f"t={row['t_s']:.3f}s x={row['ab_x']:.3f} v={row['ab_v']:.3f} "
        f"angle={row['angle']:.2f} target_angle={row['target_angle']:.2f}{seq}"
    )


def value_at_crossing(rows, x_value, direction, key):
    row = row_at_crossing(rows, x_value, direction)
    return row[key] if row else float("nan")


def print_crossings(valid, direction):
    if direction > 0:
        points = (1.0, 2.0, 3.0, 4.0, 5.0)
        label = "crossings upward"
    else:
        points = (4.0, 2.0, 0.0, -2.0, -4.0, -5.0)
        label = "crossings downward"
    print(f"  {label}:")
    for x in points:
        row = row_at_crossing(valid, x, direction)
        print(f"    {x:g}cm: {fmt_row(row)}")


def print_brake_summary(valid, target, direction):
    if direction > 0:
        start_x = 3.0
        mid_x = 4.0
        target_label = "3cm -> target"
        expected = "target_angle should drop below feedforward if +5 braking is active"
    else:
        start_x = 0.0
        mid_x = -2.0
        target_label = "0cm -> target"
        expected = "target_angle should lift above feedforward if -5 braking is active"

    start = row_at_crossing(valid, start_x, direction)
    mid = row_at_crossing(valid, mid_x, direction)
    end = row_at_crossing(valid, target, direction)

    print(f"  braking {target_label}:")
    print(f"    start: {fmt_row(start)}")
    print(f"    mid:   {fmt_row(mid)}")
    print(f"    target:{fmt_row(end)}")
    if start and end:
        dv = end["ab_v"] - start["ab_v"]
        da = end["angle"] - start["angle"]
        dta = end["target_angle"] - start["target_angle"]
        print(f"    delta_v: {dv:.3f}cm/s")
        print(f"    angle change: {da:.3f}deg")
        print(f"    target_angle change: {dta:.3f}deg")
    else:
        print("    delta_v: NA")
        print("    angle change: NA")
        print("    target_angle change: NA")

    brake_rows = segment_between(valid, start_x, target, direction)
    if brake_rows:
        print(
            "    brake_region angle min/max: "
            f"{min(r['angle'] for r in brake_rows):.2f} / {max(r['angle'] for r in brake_rows):.2f}deg"
        )
        print(
            "    brake_region target_angle min/max: "
            f"{min(r['target_angle'] for r in brake_rows):.2f} / {max(r['target_angle'] for r in brake_rows):.2f}deg"
        )
    else:
        print("    brake_region angle min/max: NA")
        print("    brake_region target_angle min/max: NA")
    print(f"    expected: {expected}")


def print_target_neighborhood(valid, target, direction):
    if not valid:
        return
    if direction > 0:
        rows = [r for r in valid if target - 1.2 <= r["ab_x"] <= target + 0.8]
    else:
        rows = [r for r in valid if target - 0.8 <= r["ab_x"] <= target + 1.2]
    if not rows:
        return
    print("  target-neighborhood trace:")
    sample_count = min(10, len(rows))
    if sample_count <= 1:
        picks = rows
    else:
        picks = [rows[round(i * (len(rows) - 1) / (sample_count - 1))] for i in range(sample_count)]
    previous = None
    for row in picks:
        if previous is None:
            print(
                f"    t={row['t_s']:.3f}s x={row['ab_x']:.3f} v={row['ab_v']:.3f} "
                f"angle={row['angle']:.2f} target_angle={row['target_angle']:.2f} "
            )
        else:
            print(
                f"    t={row['t_s']:.3f}s x={row['ab_x']:.3f} v={row['ab_v']:.3f} "
                f"angle={row['angle']:.2f} target_angle={row['target_angle']:.2f} "
                f"d_target_angle={row['target_angle'] - previous['target_angle']:.2f}"
            )
        previous = row


def summarize_leg(name, rows, target, direction):
    valid = [r for r in rows if r.get("valid", 1.0) >= 0.5]
    if not valid:
        print(f"{name}: no valid rows")
        return

    xs = [r["ab_x"] for r in valid]
    vs = [r["ab_v"] for r in valid]
    angles = [r["angle"] for r in valid]
    targets = [r["target_angle"] for r in valid]
    final_rows = valid[-min(len(valid), 200):]
    cross = first_crossing(valid, target, direction)

    if direction > 0:
        extreme_x = max(xs)
        overshoot = max(0.0, extreme_x - target)
        extreme_label = "max"
    else:
        extreme_x = min(xs)
        overshoot = max(0.0, target - extreme_x)
        extreme_label = "min"

    print(f"{name}:")
    print(f"  samples/valid_rate: {len(rows)} / {100.0 * len(valid) / max(1, len(rows)):.2f}%")
    print(
        f"  x_start/final/{extreme_label}: "
        f"{valid[0]['ab_x']:.3f} / {valid[-1]['ab_x']:.3f} / {extreme_x:.3f}cm"
    )
    print(f"  target_cross: {fmt_row(cross)}")
    print(f"  overshoot_past_target: {overshoot:.3f}cm")
    print(f"  terminal_x mean/std last ~1s: {mean(r['ab_x'] for r in final_rows):.3f} / {std(r['ab_x'] for r in final_rows):.3f}cm")
    print(f"  terminal_v mean last ~1s: {mean(r['ab_v'] for r in final_rows):.3f}cm/s")
    print(f"  angle min/mean/max: {min(angles):.2f} / {mean(angles):.2f} / {max(angles):.2f}deg")
    print(f"  target_angle min/mean/max: {min(targets):.2f} / {mean(targets):.2f} / {max(targets):.2f}deg")
    print(f"  v rms/p95-ish maxabs: {math.sqrt(mean(v * v for v in vs)):.3f} / {max(abs(v) for v in vs):.3f}cm/s")
    print_crossings(valid, direction)
    print_brake_summary(valid, target, direction)
    print_target_neighborhood(valid, target, direction)

    if cross is not None:
        print("  after target crossing:")
        for dt in (0.2, 0.4, 0.8, 1.2):
            row = row_at_or_after(valid, cross["t_s"] + dt)
            print(f"    +{dt:.1f}s: {fmt_row(row)}")


def print_transition(rows):
    phases = [r["phase"] for r in rows]
    if "minus5" not in phases:
        return
    seq_turn = next((r for r in rows if r.get("seq_stage", 0.0) >= 2.0), None)
    if seq_turn is not None:
        print(f"device sequence turn trigger: {fmt_row(seq_turn)} target_x={seq_turn['target_x']:.2f}")
    idx = next(i for i, phase in enumerate(phases) if phase == "minus5")
    lo = max(0, idx - 8)
    hi = min(len(rows), idx + 12)
    print("transition trace:")
    for row in rows[lo:hi]:
        print(
            f"  {row['phase']:>6s} t={row['t_s']:.3f}s x={row['ab_x']:.3f} "
            f"v={row['ab_v']:.3f} angle={row['angle']:.2f} "
            f"target_angle={row['target_angle']:.2f} target_x={row['target_x']:.2f}"
        )

    applied = next((r for r in rows[idx:] if r["target_x"] < 0.0 or r["target_angle"] < 22.0), None)
    if applied is not None:
        applied_idx = rows.index(applied)
        lo = max(0, applied_idx - 5)
        hi = min(len(rows), applied_idx + 10)
        print("transition applied trace:")
        for row in rows[lo:hi]:
            print(
                f"  {row['phase']:>6s} t={row['t_s']:.3f}s x={row['ab_x']:.3f} "
                f"v={row['ab_v']:.3f} angle={row['angle']:.2f} "
                f"target_angle={row['target_angle']:.2f} target_x={row['target_x']:.2f}"
            )
    else:
        print("transition applied trace: NA")


def print_control_input_summary(rows):
    if not rows or not {"control_ms", "control_x", "control_v"}.issubset(rows[0]):
        return
    updates = []
    last_ms = None
    for row in rows:
        control_ms = int(row["control_ms"])
        if control_ms == 0 or control_ms == last_ms:
            continue
        updates.append(row)
        last_ms = control_ms
    if not updates:
        print("outer-loop inputs: no completed update captured")
        return
    intervals = [
        (int(b["control_ms"]) - int(a["control_ms"])) & 0xFFFFFFFF
        for a, b in zip(updates, updates[1:])
    ]
    observed_lag = [
        (int(row["stm32_ms"]) - int(row["control_ms"])) & 0xFFFFFFFF
        for row in updates
    ]
    print(f"outer-loop input updates: {len(updates)} (distinct control_ms)")
    if intervals:
        ordered = sorted(intervals)
        print(
            f"  period_ms min/median/max: "
            f"{ordered[0]} / {ordered[len(ordered) // 2]} / {ordered[-1]}"
        )
    print(
        f"  first telemetry after update median/max: "
        f"{sorted(observed_lag)[len(observed_lag) // 2]} / {max(observed_lag)}ms"
    )
    print("  control_x/control_v are cached at the update, not decimated telemetry estimates")


def print_velocity_test_summary(rows):
    updates = []
    last_ms = None
    for row in rows:
        stamp = int(row.get("control_ms", 0))
        if stamp and stamp != last_ms:
            updates.append(row)
            last_ms = stamp
    if not updates:
        print("velocity test: no outer-loop updates captured")
        return
    print("velocity test (20 ms outer-loop updates):")
    for phase in ("speed_step",):
        segment = [r for r in updates if r["phase"] == phase]
        if not segment:
            print(f"  {phase}: no samples")
            continue
        errors = [r["target_v"] - r["control_v"] for r in segment]
        angle_errors = [r["target_angle"] - r["angle"] for r in segment]
        print(
            f"  {phase}: updates={len(segment)} "
            f"t={segment[0]['t_s']:.3f}..{segment[-1]['t_s']:.3f}s "
            f"x={segment[0]['control_x']:.2f}..{segment[-1]['control_x']:.2f}cm "
            f"target_v={mean(r['target_v'] for r in segment):+.2f}cm/s "
            f"v mean/min/max={mean(r['control_v'] for r in segment):+.2f}/"
            f"{min(r['control_v'] for r in segment):+.2f}/"
            f"{max(r['control_v'] for r in segment):+.2f}cm/s "
            f"error mean/peak_abs={mean(errors):+.2f}/{max(map(abs, errors)):.2f}cm/s "
            f"angle_error peak_abs={max(map(abs, angle_errors)):.2f}deg"
        )
        print(f"    first: {fmt_row(segment[0])} target_v={segment[0]['target_v']:+.2f}")
        print(f"    last:  {fmt_row(segment[-1])} target_v={segment[-1]['target_v']:+.2f}")
    ending = next((r for r in rows if r["phase"] in ("speed_done", "speed_abort")), None)
    print(f"  exit: {ending['phase'] if ending else 'not captured'} "
          f"{fmt_row(ending) if ending else ''}")
    print("  speed-loop gains come from the recorded tuning settings; compare runs with those settings recorded")


def main():
    parser = argparse.ArgumentParser(description="Analyze 0cm -> +5cm -> -5cm sequence capture.")
    parser.add_argument("csv")
    args = parser.parse_args()

    rows = load_rows(args.csv)
    print(f"file: {args.csv}")
    if not rows:
        print("no rows")
        return
    print(f"samples/duration: {len(rows)} / {rows[-1]['t_s'] - rows[0]['t_s']:.3f}s")
    print_control_input_summary(rows)
    print()

    if any(row["phase"].startswith("speed_") for row in rows):
        if not all("target_v" in row for row in rows):
            print("velocity test requires target_v in the control CSV")
            return
        print_velocity_test_summary(rows)
        return

    # Task1 restart may contain a pre-positioning interval at target_x=0.
    # Do not mistake that interval for the +5 leg.
    plus = [r for r in rows if r["phase"] == "plus5" and r.get("target_x", 5.0) > 0.5]
    minus = [r for r in rows if r["phase"] == "minus5" and r.get("target_x", -5.0) < -0.5]
    summarize_leg("plus5", plus, 5.0, 1)
    print("=" * 80)
    summarize_leg("minus5", minus, -5.0, -1)
    print("=" * 80)
    print_transition(rows)


if __name__ == "__main__":
    main()
