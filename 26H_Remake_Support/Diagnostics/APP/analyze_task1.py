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
                for key in ("bbp", "bpush", "btrim", "bterm", "bstall", "bbp_deg", "trim_deg", "seq_stage"):
                    parsed.setdefault(key, 0.0)
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
    flags = ""
    active = [name for name in ("bbp", "bpush", "btrim", "bterm", "bstall") if row.get(name, 0.0) >= 0.5]
    if active:
        flags = " flags=" + "+".join(active)
    seq = ""
    if row.get("seq_stage", 0.0) > 0.0:
        seq = f" seq={int(row.get('seq_stage', 0.0))}"
    return (
        f"t={row['t_s']:.3f}s x={row['ab_x']:.3f} v={row['ab_v']:.3f} "
        f"angle={row['angle']:.2f} target_angle={row['target_angle']:.2f}{flags}{seq}"
    )


def fmt_num(value, suffix=""):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NA"
    return f"{value:.3f}{suffix}"


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


def print_state_flag_summary(valid):
    if not valid:
        return
    print("  state flags:")
    for key, label in (
        ("bbp", "bbp brake"),
        ("bpush", "terminal push"),
        ("btrim", "terminal trim"),
        ("bterm", "terminal brake gate"),
        ("bstall", "stalled-before-terminal gate"),
    ):
        rows = [r for r in valid if r.get(key, 0.0) >= 0.5]
        if not rows:
            print(f"    {label}: none")
            continue
        print(
            f"    {label}: {len(rows)} samples, "
            f"t={rows[0]['t_s']:.3f}->{rows[-1]['t_s']:.3f}s, "
            f"x={rows[0]['ab_x']:.3f}->{rows[-1]['ab_x']:.3f}cm, "
            f"v={rows[0]['ab_v']:.3f}->{rows[-1]['ab_v']:.3f}cm/s"
        )
        if key == "bbp":
            vals = [r.get("bbp_deg", 0.0) for r in rows]
            print(f"      bbp_deg min/mean/max: {min(vals):.3f} / {mean(vals):.3f} / {max(vals):.3f}deg")
        elif key in ("bpush", "btrim"):
            vals = [r.get("trim_deg", 0.0) for r in rows]
            print(f"      trim_deg min/mean/max: {min(vals):.3f} / {mean(vals):.3f} / {max(vals):.3f}deg")


def active_segments(valid, key):
    segments = []
    current = []
    for row in valid:
        if row.get(key, 0.0) >= 0.5:
            current.append(row)
        elif current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return segments


def effort_deg_s(rows, key):
    if len(rows) < 2:
        return 0.0
    total = 0.0
    for prev, cur in zip(rows, rows[1:]):
        dt = max(0.0, cur["t_s"] - prev["t_s"])
        total += abs(prev.get(key, 0.0)) * dt
    return total


def print_process_efficiency(valid, target, direction, base_angle_deg):
    if not valid:
        return
    print("  process efficiency:")

    bbp_segments = active_segments(valid, "bbp")
    if not bbp_segments:
        print("    bbp release: no bbp segment")
    else:
        for idx, seg in enumerate(bbp_segments, 1):
            first = seg[0]
            last = seg[-1]
            start_err = abs(target - first["ab_x"])
            end_err = abs(target - last["ab_x"])
            release_side = side_of_target(last, target, direction)
            print(
                f"    bbp segment {idx}: t={first['t_s']:.3f}->{last['t_s']:.3f}s "
                f"dur={last['t_s'] - first['t_s']:.3f}s "
                f"x={first['ab_x']:.3f}->{last['ab_x']:.3f} "
                f"v={first['ab_v']:.3f}->{last['ab_v']:.3f} "
                f"abs_err={start_err:.3f}->{end_err:.3f} "
                f"release_side={release_side} "
                f"bbp_deg={first.get('bbp_deg', 0.0):.2f}->{last.get('bbp_deg', 0.0):.2f}"
            )
            print("      after bbp release:")
            for dt in (0.2, 0.4, 0.8):
                row = row_at_or_after(valid, last["t_s"] + dt)
                if row is None:
                    print(f"        +{dt:.1f}s: NA")
                    continue
                err = abs(target - row["ab_x"])
                print(
                    f"        +{dt:.1f}s: x={row['ab_x']:.3f} v={row['ab_v']:.3f} "
                    f"abs_err={err:.3f} target_angle={row['target_angle']:.2f} "
                    f"bbp={row.get('bbp_deg', 0.0):.2f} trim={row.get('trim_deg', 0.0):.2f}"
                )

    for key, label in (("bpush", "terminal push"), ("btrim", "terminal trim")):
        segments = active_segments(valid, key)
        if not segments:
            print(f"    {label} efficiency: none")
            continue
        for idx, seg in enumerate(segments, 1):
            first = seg[0]
            last = seg[-1]
            start_err = abs(target - first["ab_x"])
            end_err = abs(target - last["ab_x"])
            improvement = start_err - end_err
            dx = last["ab_x"] - first["ab_x"]
            dur = max(0.0, last["t_s"] - first["t_s"])
            trim_vals = [r.get("trim_deg", 0.0) for r in seg]
            trim_work = effort_deg_s(seg, "trim_deg")
            per_deg_s = improvement / trim_work if trim_work > 1.0e-6 else float("nan")
            mean_abs_v = mean(abs(r["ab_v"]) for r in seg)
            helpful = [
                toward_target_helpful(target - r["ab_x"], r["target_angle"] - base_angle_deg)
                for r in seg
            ]
            helpful_rate = 100.0 * sum(helpful) / len(helpful) if helpful else float("nan")
            print(
                f"    {label} segment {idx}: t={first['t_s']:.3f}->{last['t_s']:.3f}s "
                f"dur={dur:.3f}s x={first['ab_x']:.3f}->{last['ab_x']:.3f} "
                f"dx={dx:.3f} abs_err={start_err:.3f}->{end_err:.3f} "
                f"improvement={improvement:.3f}cm mean|v|={mean_abs_v:.3f}"
            )
            print(
                f"      trim_deg min/mean/max={min(trim_vals):.3f}/{mean(trim_vals):.3f}/{max(trim_vals):.3f} "
                f"deg_s={trim_work:.3f} improvement_per_deg_s={fmt_num(per_deg_s, 'cm/deg/s')} "
                f"helpful_sign_rate={helpful_rate:.1f}%"
            )
            if dur >= 0.5 and improvement < 0.2:
                print("      warning: long terminal action with little position improvement")


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
                f"bbp_deg={row.get('bbp_deg', 0.0):.2f} trim_deg={row.get('trim_deg', 0.0):.2f}"
            )
        else:
            print(
                f"    t={row['t_s']:.3f}s x={row['ab_x']:.3f} v={row['ab_v']:.3f} "
                f"angle={row['angle']:.2f} target_angle={row['target_angle']:.2f} "
                f"bbp_deg={row.get('bbp_deg', 0.0):.2f} trim_deg={row.get('trim_deg', 0.0):.2f} "
                f"d_target_angle={row['target_angle'] - previous['target_angle']:.2f}"
            )
        previous = row


def print_terminal_trim_summary(valid,
                                target,
                                direction,
                                base_angle_deg,
                                trim_window_cm,
                                trim_v_window_cm,
                                trim_deadband_cm):
    if not valid:
        return
    terminal_rows = [r for r in valid if abs(target - r["ab_x"]) <= trim_window_cm]
    if not terminal_rows:
        print("  terminal trim window: no samples")
        return

    opportunity_rows = [
        r for r in terminal_rows
        if abs(target - r["ab_x"]) > trim_deadband_cm and abs(r["ab_v"]) <= trim_v_window_cm
    ]
    offsets = [r["target_angle"] - base_angle_deg for r in terminal_rows]
    opportunity_offsets = [r["target_angle"] - base_angle_deg for r in opportunity_rows]
    helpful = []
    for r in opportunity_rows:
        error = target - r["ab_x"]
        offset = r["target_angle"] - base_angle_deg
        if abs(offset) < 1.0e-4:
            helpful.append(False)
        else:
            helpful.append((error * offset) > 0.0)

    first = terminal_rows[0]
    last = terminal_rows[-1]
    min_abs_error = min(abs(target - r["ab_x"]) for r in terminal_rows)
    last_abs_error = abs(target - last["ab_x"])
    helpful_rate = 100.0 * sum(1 for x in helpful if x) / len(helpful) if helpful else float("nan")

    print("  terminal trim analysis:")
    print(
        f"    window +/-{trim_window_cm:g}cm entered: "
        f"t={first['t_s']:.3f}s x={first['ab_x']:.3f} v={first['ab_v']:.3f}"
    )
    print(
        f"    terminal last: t={last['t_s']:.3f}s x={last['ab_x']:.3f} "
        f"error={target - last['ab_x']:.3f} abs_error={last_abs_error:.3f}cm"
    )
    print(f"    terminal min_abs_error: {min_abs_error:.3f}cm")
    print(f"    low-speed trim opportunities: {len(opportunity_rows)} samples")
    print(
        "    target_angle - feedforward baseline min/mean/max: "
        f"{min(offsets):.3f} / {mean(offsets):.3f} / {max(offsets):.3f}deg"
    )
    if opportunity_offsets:
        print(
            "    opportunity offset min/mean/max: "
            f"{min(opportunity_offsets):.3f} / {mean(opportunity_offsets):.3f} / "
            f"{max(opportunity_offsets):.3f}deg"
        )
        print(f"    opportunity helpful_sign_rate: {helpful_rate:.1f}%")
    else:
        print("    opportunity offset min/mean/max: NA")
        print("    opportunity helpful_sign_rate: NA")


def side_of_target(row, target, direction):
    err = target - row["ab_x"]
    if abs(err) < 1.0e-6:
        return "at"
    if direction > 0:
        return "before" if err > 0.0 else "past"
    return "before" if err < 0.0 else "past"


def toward_target_helpful(error, offset):
    if abs(offset) < 1.0e-4:
        return False
    return error * offset > 0.0


def summarize_opportunity_group(label, rows, target, base_angle_deg):
    print(f"    {label}: {len(rows)} samples")
    if not rows:
        return
    first = rows[0]
    last = rows[-1]
    offsets = [r["target_angle"] - base_angle_deg for r in rows]
    abs_errors = [abs(target - r["ab_x"]) for r in rows]
    helpful = [
        toward_target_helpful(target - r["ab_x"], r["target_angle"] - base_angle_deg)
        for r in rows
    ]
    print(
        f"      first: t={first['t_s']:.3f}s x={first['ab_x']:.3f} "
        f"v={first['ab_v']:.3f} offset={first['target_angle'] - base_angle_deg:.3f}deg"
    )
    print(
        f"      last:  t={last['t_s']:.3f}s x={last['ab_x']:.3f} "
        f"v={last['ab_v']:.3f} offset={last['target_angle'] - base_angle_deg:.3f}deg"
    )
    print(
        "      abs_error min/mean/max: "
        f"{min(abs_errors):.3f} / {mean(abs_errors):.3f} / {max(abs_errors):.3f}cm"
    )
    print(
        "      offset min/mean/max: "
        f"{min(offsets):.3f} / {mean(offsets):.3f} / {max(offsets):.3f}deg"
    )
    print(f"      helpful_sign_rate: {100.0 * sum(helpful) / len(helpful):.1f}%")


def print_terminal_correction_diagnosis(valid,
                                        target,
                                        direction,
                                        base_angle_deg,
                                        trim_window_cm,
                                        trim_v_window_cm,
                                        trim_deadband_cm):
    terminal_rows = [r for r in valid if abs(target - r["ab_x"]) <= trim_window_cm]
    if not terminal_rows:
        return

    low_speed = [
        r for r in terminal_rows
        if abs(target - r["ab_x"]) > trim_deadband_cm and abs(r["ab_v"]) <= trim_v_window_cm
    ]
    before = [r for r in low_speed if side_of_target(r, target, direction) == "before"]
    past = [r for r in low_speed if side_of_target(r, target, direction) == "past"]

    print("  terminal correction diagnosis:")
    print(
        f"    configured trim: window=+/-{trim_window_cm:g}cm, "
        f"|v|<={trim_v_window_cm:g}cm/s, deadband={trim_deadband_cm:g}cm"
    )
    summarize_opportunity_group("before-target low-speed push zone", before, target, base_angle_deg)
    summarize_opportunity_group("past-target low-speed return zone", past, target, base_angle_deg)

    first_past = next((r for r in terminal_rows if side_of_target(r, target, direction) == "past"), None)
    first_past_slow = past[0] if past else None
    if first_past:
        print(
            f"    first past target: t={first_past['t_s']:.3f}s x={first_past['ab_x']:.3f} "
            f"v={first_past['ab_v']:.3f} offset={first_past['target_angle'] - base_angle_deg:.3f}deg"
        )
    if first_past_slow:
        print(
            f"    first past-target trim opportunity: t={first_past_slow['t_s']:.3f}s "
            f"x={first_past_slow['ab_x']:.3f} v={first_past_slow['ab_v']:.3f} "
            f"offset={first_past_slow['target_angle'] - base_angle_deg:.3f}deg"
        )
        print("    return after first past-target opportunity:")
        start_err = abs(target - first_past_slow["ab_x"])
        for dt in (0.2, 0.4, 0.8, 1.2):
            row = row_at_or_after(valid, first_past_slow["t_s"] + dt)
            if row is None:
                print(f"      +{dt:.1f}s: NA")
                continue
            err = abs(target - row["ab_x"])
            print(
                f"      +{dt:.1f}s: x={row['ab_x']:.3f} v={row['ab_v']:.3f} "
                f"offset={row['target_angle'] - base_angle_deg:.3f}deg "
                f"abs_error={err:.3f}cm improvement={start_err - err:.3f}cm"
            )

    max_past = max((abs(target - r["ab_x"]) for r in terminal_rows
                    if side_of_target(r, target, direction) == "past"), default=float("nan"))
    final = terminal_rows[-1]
    final_err = target - final["ab_x"]
    final_offset = final["target_angle"] - base_angle_deg
    print(
        f"    past-side max_abs_error_in_window: {fmt_num(max_past, 'cm')}"
    )
    print(
        f"    final terminal state: x={final['ab_x']:.3f} error={final_err:.3f} "
        f"offset={final_offset:.3f}deg"
    )


def print_trim_threshold_sweep(valid,
                               target,
                               base_angle_deg,
                               trim_window_cm,
                               trim_deadband_cm):
    terminal_rows = [r for r in valid if abs(target - r["ab_x"]) <= trim_window_cm]
    if not terminal_rows:
        return
    print("  trim velocity-threshold sweep:")
    for v_limit in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        rows = [
            r for r in terminal_rows
            if abs(target - r["ab_x"]) > trim_deadband_cm and abs(r["ab_v"]) <= v_limit
        ]
        if rows:
            first = rows[0]
            print(
                f"    |v|<={v_limit:.1f}: first t={first['t_s']:.3f}s "
                f"x={first['ab_x']:.3f} v={first['ab_v']:.3f} "
                f"offset={first['target_angle'] - base_angle_deg:.3f}deg samples={len(rows)}"
            )
        else:
            print(f"    |v|<={v_limit:.1f}: no samples")


def summarize_leg(name,
                  rows,
                  target,
                  direction,
                  base_angle_deg,
                  trim_window_cm,
                  trim_v_window_cm,
                  trim_deadband_cm):
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
    print_state_flag_summary(valid)
    print_process_efficiency(valid, target, direction, base_angle_deg)
    print_target_neighborhood(valid, target, direction)
    print_terminal_trim_summary(valid,
                                target,
                                direction,
                                base_angle_deg,
                                trim_window_cm,
                                trim_v_window_cm,
                                trim_deadband_cm)
    print_terminal_correction_diagnosis(valid,
                                        target,
                                        direction,
                                        base_angle_deg,
                                        trim_window_cm,
                                        trim_v_window_cm,
                                        trim_deadband_cm)
    print_trim_threshold_sweep(valid,
                               target,
                               base_angle_deg,
                               trim_window_cm,
                               trim_deadband_cm)

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


def main():
    parser = argparse.ArgumentParser(description="Analyze 0cm -> +5cm -> -5cm sequence capture.")
    parser.add_argument("csv")
    parser.add_argument("--ba", type=float, default=22.0)
    parser.add_argument("--p-bff", type=float, default=0.7)
    parser.add_argument("--m-bff", type=float, default=0.4)
    parser.add_argument("--trim-window", type=float, default=1.0)
    parser.add_argument("--trim-v", type=float, default=2.5)
    parser.add_argument("--trim-deadband", type=float, default=0.15)
    args = parser.parse_args()

    rows = load_rows(args.csv)
    print(f"file: {args.csv}")
    if not rows:
        print("no rows")
        return
    print(f"samples/duration: {len(rows)} / {rows[-1]['t_s'] - rows[0]['t_s']:.3f}s")
    print()

    # Task1 restart may contain a pre-positioning interval at target_x=0.
    # Do not mistake that interval for the +5 leg.
    plus = [r for r in rows if r["phase"] == "plus5" and r.get("target_x", 5.0) > 0.5]
    minus = [r for r in rows if r["phase"] == "minus5" and r.get("target_x", -5.0) < -0.5]
    summarize_leg("plus5",
                  plus,
                  5.0,
                  1,
                  args.ba + args.p_bff * 5.0,
                  args.trim_window,
                  args.trim_v,
                  args.trim_deadband)
    print("=" * 80)
    summarize_leg("minus5",
                  minus,
                  -5.0,
                  -1,
                  args.ba + args.m_bff * -5.0,
                  args.trim_window,
                  args.trim_v,
                  args.trim_deadband)
    print("=" * 80)
    print_transition(rows)


if __name__ == "__main__":
    main()
