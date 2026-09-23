import argparse
import csv
import re
import time
from pathlib import Path

import serial


NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
CHANNELS = [
    "ab_x",
    "target_x",
    "ab_v",
    "angle",
    "target_angle",
    "bbp_deg",
    "trim_deg",
    "bbp",
    "bpush",
    "btrim",
    "bterm",
    "seq_stage",
    "age_ms",
]
PRE_SEQ_STATUS_CHANNELS = [
    "ab_x",
    "target_x",
    "ab_v",
    "angle",
    "target_angle",
    "bbp_deg",
    "trim_deg",
    "bbp",
    "bpush",
    "btrim",
    "bterm",
    "age_ms",
]
LEGACY_STATUS_CHANNELS = [
    "ab_x",
    "target_x",
    "ab_v",
    "angle",
    "target_angle",
    "bbp",
    "bpush",
    "btrim",
    "bterm",
    "bstall",
    "valid",
    "age_ms",
]
LEGACY_VOFA_CHANNELS = [
    "raw_x",
    "target_x",
    "ab_x",
    "ab_v",
    "angle",
    "target_angle",
    "control_x",
    "current",
    "valid",
    "seq",
    "age_ms",
]
HEADER = ["t_s", "phase"] + CHANNELS


def unique_output_path(path, overwrite=False):
    path = Path(path)
    if overwrite or not path.exists():
        return path
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.stem}_{stamp}{path.suffix}")


def parse_line(line):
    nums = [float(x) for x in NUMBER_RE.findall(line)]
    if len(nums) >= len(CHANNELS):
        nums = nums[-len(CHANNELS):]
        return dict(zip(CHANNELS, nums))
    if len(nums) >= len(PRE_SEQ_STATUS_CHANNELS):
        nums = nums[-len(PRE_SEQ_STATUS_CHANNELS):]
        vals = dict(zip(PRE_SEQ_STATUS_CHANNELS, nums))
        vals["seq_stage"] = 0.0
        return {key: vals.get(key, 0.0) for key in CHANNELS}
    if len(nums) >= len(LEGACY_STATUS_CHANNELS):
        nums = nums[-len(LEGACY_STATUS_CHANNELS):]
        vals = dict(zip(LEGACY_STATUS_CHANNELS, nums))
        vals["bbp_deg"] = 0.0
        vals["trim_deg"] = 0.0
        vals["seq_stage"] = 0.0
        return {key: vals.get(key, 0.0) for key in CHANNELS}
    if len(nums) >= len(LEGACY_VOFA_CHANNELS):
        nums = nums[-len(LEGACY_VOFA_CHANNELS):]
        vals = dict(zip(LEGACY_VOFA_CHANNELS, nums))
        return {
            "ab_x": vals["ab_x"],
            "target_x": vals["target_x"],
            "ab_v": vals["ab_v"],
            "angle": vals["angle"],
            "target_angle": vals["target_angle"],
            "bbp_deg": 0.0,
            "trim_deg": 0.0,
            "bbp": 0.0,
            "bpush": 0.0,
            "btrim": 0.0,
            "bterm": 0.0,
            "seq_stage": 0.0,
            "age_ms": vals["age_ms"],
        }
    else:
        return None


def send_command(ser, cmd, delay_s):
    print(f"  > {cmd}", flush=True)
    ser.write((cmd + "\r\n").encode("utf-8"))
    ser.flush()
    time.sleep(delay_s)


def send_commands(ser, commands, delay_s):
    for cmd in commands:
        send_command(ser, cmd, delay_s)


def send_step_command(ser, target, expected_target_angle, retries, retry_s, tol=0.2):
    print("command: > ball on", flush=True)
    ser.write(b"ball on\r\n")
    ser.flush()
    time.sleep(0.05)

    cmd = f"bt {target:g}"
    for attempt in range(1, retries + 1):
        print(f"command: > {cmd}", flush=True)
        ser.write((cmd + "\r\n").encode("utf-8"))
        ser.flush()

        deadline = time.monotonic() + retry_s
        last_vals = None
        while time.monotonic() < deadline:
            vals = read_valid_sample(ser)
            last_vals = vals
            target_ok = abs(vals["target_x"] - target) <= 0.2
            angle_ok = abs(vals["target_angle"] - expected_target_angle) <= tol
            if target_ok and angle_ok:
                print(
                    f"bt ack: target_x={vals['target_x']:.2f} "
                    f"target_angle={vals['target_angle']:.2f}",
                    flush=True,
                )
                return vals

        if last_vals is None:
            print(f"bt not applied yet; retry {attempt + 1}/{retries}", flush=True)
        else:
            print(
                f"bt not applied yet; retry {attempt + 1}/{retries}: "
                f"target_x={last_vals['target_x']:.2f} "
                f"target_angle={last_vals['target_angle']:.2f}",
                flush=True,
            )

    raise SystemExit("bt command was not acknowledged; abort capture")


def read_valid_sample(ser):
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        vals = parse_line(line)
        if vals is not None:
            return vals


def is_valid_sample(vals):
    return vals.get("valid", 1.0) >= 0.5


def wait_gate(ser, label, x, x_tol, v_tol, angle, angle_tol, stable_s, timeout_s, print_ms):
    print(f"waiting for {label} gate:", flush=True)
    print(
        f"  x={x:g}+/-{x_tol:g}cm, |v|<={v_tol:g}cm/s, "
        f"angle={angle:g}+/-{angle_tol:g}deg",
        flush=True,
    )
    start = time.monotonic()
    stable_since = None
    last_print = 0.0
    while True:
        now = time.monotonic()
        if (now - start) >= timeout_s:
            raise SystemExit(f"{label} gate timeout")
        vals = read_valid_sample(ser)
        ok = (
            is_valid_sample(vals)
            and abs(vals["ab_x"] - x) <= x_tol
            and abs(vals["ab_v"]) <= v_tol
            and abs(vals["angle"] - angle) <= angle_tol
        )
        if ok:
            stable_since = now if stable_since is None else stable_since
            if (now - stable_since) >= stable_s:
                print(
                    f"{label} gate ok: x={vals['ab_x']:.2f}, "
                    f"v={vals['ab_v']:.2f}, angle={vals['angle']:.2f}",
                    flush=True,
                )
                return vals
        else:
            stable_since = None

        if (now - last_print) * 1000.0 >= print_ms:
            last_print = now
            print(
                f"wait {label} x={vals['ab_x']:6.2f} v={vals['ab_v']:7.2f} "
                f"angle={vals['angle']:6.2f} target_angle={vals['target_angle']:6.2f} "
                f"age={vals['age_ms']:4.0f}",
                flush=True,
            )


def wait_target_settle(ser, writer, rows, start_time, label, target, x_tol, v_tol, hold_s, timeout_s, print_ms):
    print(
        f"waiting for {label} settle: x={target:g}+/-{x_tol:g}cm, "
        f"|v|<={v_tol:g}cm/s for {hold_s:g}s",
        flush=True,
    )
    wait_start = time.monotonic()
    stable_since = None
    last_print = 0.0
    last_vals = None
    while True:
        now = time.monotonic()
        t_s = now - start_time
        if (now - wait_start) >= timeout_s:
            print(f"warning: {label} settle timeout", flush=True)
            raise SystemExit(f"{label} did not settle; abort transition")

        vals = read_valid_sample(ser)
        last_vals = vals
        row = {"t_s": t_s, "phase": label, **vals}
        rows.append(row)
        writer.writerow(row)

        ok = is_valid_sample(vals) and abs(vals["ab_x"] - target) <= x_tol and abs(vals["ab_v"]) <= v_tol
        if ok:
            stable_since = now if stable_since is None else stable_since
            if (now - stable_since) >= hold_s:
                print(
                    f"{label} settle ok: t={t_s:.2f}s x={vals['ab_x']:.2f}, "
                    f"v={vals['ab_v']:.2f}, angle={vals['angle']:.2f}",
                    flush=True,
                )
                return vals
        else:
            stable_since = None

        if (now - last_print) * 1000.0 >= print_ms:
            last_print = now
            print(
                f"REC {label} t={t_s:5.2f}s x={vals['ab_x']:7.2f} "
                f"v={vals['ab_v']:7.2f} angle={vals['angle']:6.2f} "
                f"target_angle={vals['target_angle']:6.2f} age={vals['age_ms']:4.0f}",
                flush=True,
            )


def wait_x_band_settle(ser,
                       writer,
                       rows,
                       start_time,
                       label,
                       min_x,
                       max_x,
                       x_eps,
                       v_tol,
                       hold_s,
                       timeout_s,
                       print_ms):
    print(
        f"waiting for {label} settle: x in [{min_x:g}, {max_x:g}]cm, "
        f"|v|<={v_tol:g}cm/s for {hold_s:g}s",
        flush=True,
    )
    wait_start = time.monotonic()
    stable_since = None
    last_print = 0.0
    while True:
        now = time.monotonic()
        t_s = now - start_time
        if (now - wait_start) >= timeout_s:
            print(f"warning: {label} settle timeout", flush=True)
            raise SystemExit(f"{label} did not settle; abort transition")

        vals = read_valid_sample(ser)
        row = {"t_s": t_s, "phase": label, **vals}
        rows.append(row)
        writer.writerow(row)

        ok = (
            is_valid_sample(vals)
            and (min_x - x_eps) <= vals["ab_x"] <= (max_x + x_eps)
            and abs(vals["ab_v"]) <= v_tol
        )
        if ok:
            stable_since = now if stable_since is None else stable_since
            if (now - stable_since) >= hold_s:
                print(
                    f"{label} settle ok: t={t_s:.2f}s x={vals['ab_x']:.2f}, "
                    f"v={vals['ab_v']:.2f}, angle={vals['angle']:.2f}",
                    flush=True,
                )
                return vals
        else:
            stable_since = None

        if (now - last_print) * 1000.0 >= print_ms:
            last_print = now
            print(
                f"REC {label} t={t_s:5.2f}s x={vals['ab_x']:7.2f} "
                f"v={vals['ab_v']:7.2f} angle={vals['angle']:6.2f} "
                f"target_angle={vals['target_angle']:6.2f} age={vals['age_ms']:4.0f}",
                flush=True,
            )


def wait_target_turn_gate(ser,
                          writer,
                          rows,
                          start_time,
                          label,
                          target_x,
                          x_window,
                          v_tol,
                          hold_s,
                          timeout_s,
                          print_ms):
    print(
        f"waiting for {label} turn gate: abs(x-{target_x:g})<={x_window:g}cm, "
        f"|v|<={v_tol:g}cm/s for {hold_s:g}s",
        flush=True,
    )
    wait_start = time.monotonic()
    stable_since = None
    last_print = 0.0
    while True:
        now = time.monotonic()
        t_s = now - start_time
        if (now - wait_start) >= timeout_s:
            print(f"warning: {label} turn gate timeout", flush=True)
            raise SystemExit(f"{label} did not reach turn gate; abort transition")

        vals = read_valid_sample(ser)
        row = {"t_s": t_s, "phase": label, **vals}
        rows.append(row)
        writer.writerow(row)

        ok = (
            is_valid_sample(vals)
            and abs(vals["ab_x"] - target_x) <= x_window
            and abs(vals["ab_v"]) <= v_tol
        )
        if ok:
            stable_since = now if stable_since is None else stable_since
            if (now - stable_since) >= hold_s:
                print(
                    f"{label} turn gate ok: t={t_s:.2f}s x={vals['ab_x']:.2f}, "
                    f"v={vals['ab_v']:.2f}, angle={vals['angle']:.2f}",
                    flush=True,
                )
                return vals
        else:
            stable_since = None

        if (now - last_print) * 1000.0 >= print_ms:
            last_print = now
            print(
                f"REC {label} t={t_s:5.2f}s x={vals['ab_x']:7.2f} "
                f"v={vals['ab_v']:7.2f} angle={vals['angle']:6.2f} "
                f"target_angle={vals['target_angle']:6.2f} age={vals['age_ms']:4.0f}",
                flush=True,
            )


def capture_for(ser, writer, rows, start_time, label, duration_s, print_ms):
    phase_start = time.monotonic()
    last_print = 0.0
    while True:
        now = time.monotonic()
        if (now - phase_start) >= duration_s:
            return
        vals = read_valid_sample(ser)
        t_s = time.monotonic() - start_time
        row = {"t_s": t_s, "phase": label, **vals}
        rows.append(row)
        writer.writerow(row)
        if (now - last_print) * 1000.0 >= print_ms:
            last_print = now
            print(
                f"REC {label} t={t_s:5.2f}s x={vals['ab_x']:7.2f} "
                f"v={vals['ab_v']:7.2f} angle={vals['angle']:6.2f} "
                f"target_angle={vals['target_angle']:6.2f} age={vals['age_ms']:4.0f}",
                flush=True,
            )


def capture_device_sequence(ser, writer, rows, start_time, duration_s, print_ms):
    phase_start = time.monotonic()
    last_print = 0.0
    while True:
        now = time.monotonic()
        if (now - phase_start) >= duration_s:
            return
        vals = read_valid_sample(ser)
        t_s = time.monotonic() - start_time
        if vals["target_x"] < -0.5:
            label = "minus5"
        elif vals["target_x"] > 0.5:
            label = "plus5"
        else:
            # Firmware Task1 may spend time returning to the calibrated zero
            # before launching +5 -> -5. Keep that interval explicit.
            label = "home"
        row = {"t_s": t_s, "phase": label, **vals}
        rows.append(row)
        writer.writerow(row)
        if (now - last_print) * 1000.0 >= print_ms:
            last_print = now
            print(
                f"REC {label} t={t_s:5.2f}s x={vals['ab_x']:7.2f} "
                f"v={vals['ab_v']:7.2f} angle={vals['angle']:6.2f} "
                f"target_x={vals['target_x']:6.2f} target_angle={vals['target_angle']:6.2f} "
                f"bbp={vals['bbp_deg']:5.2f} trim={vals['trim_deg']:5.2f} "
                f"flags={int(vals['bbp'])}{int(vals['bpush'])}{int(vals['btrim'])}{int(vals['bterm'])} "
                f"seq={int(vals['seq_stage'])} "
                f"age={vals['age_ms']:4.0f}",
                flush=True,
            )


def main():
    parser = argparse.ArgumentParser(description="Auto capture 0cm -> +5cm -> -5cm sequence.")
    parser.add_argument("--port", default="COM26")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--output", default="sequence_0_to_5_to_m5.csv")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--command-delay-s", type=float, default=0.25)
    parser.add_argument("--transition-command-delay-s", type=float, default=0.08)
    parser.add_argument("--print-ms", type=float, default=300.0)
    parser.add_argument("--bt-retries", type=int, default=4)
    parser.add_argument("--bt-retry-s", type=float, default=0.35)

    parser.add_argument("--start-x", type=float, default=0.0)
    parser.add_argument("--start-x-tol", type=float, default=0.7)
    parser.add_argument("--start-v-tol", type=float, default=0.8)
    parser.add_argument("--start-angle", type=float, default=22.0)
    parser.add_argument("--start-angle-tol", type=float, default=0.8)
    parser.add_argument("--start-stable-s", type=float, default=0.4)
    parser.add_argument("--start-timeout-s", type=float, default=40.0)

    parser.add_argument("--plus-settle-min-x", type=float, default=4.3)
    parser.add_argument("--plus-settle-max-x", type=float, default=5.7)
    parser.add_argument("--plus-settle-x-eps", type=float, default=0.05)
    parser.add_argument("--plus-settle-v-tol", type=float, default=0.5)
    parser.add_argument("--plus-settle-hold-s", type=float, default=0.45)
    parser.add_argument("--plus-turn-window", type=float, default=0.5)
    parser.add_argument("--plus-turn-v-tol", type=float, default=0.6)
    parser.add_argument("--plus-turn-hold-s", type=float, default=0.05)
    parser.add_argument("--plus-use-turn-gate", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--plus-timeout-s", type=float, default=5.0)
    parser.add_argument("--minus-capture-s", type=float, default=5.0)
    parser.add_argument("--device-seq", action="store_true")
    parser.add_argument("--seq-capture-s", type=float, default=8.0)
    parser.add_argument("--seq-turn-window", type=float, default=0.7)
    parser.add_argument("--seq-turn-v", type=float, default=0.7)

    parser.add_argument("--p-ba", type=float, default=22.0)
    parser.add_argument("--p-bff", type=float, default=0.9)
    parser.add_argument("--p-bterm-x", type=float, default=0.6)
    parser.add_argument("--p-bterm-v", type=float, default=1.0)
    parser.add_argument("--p-bpush-window", type=float, default=1.8)
    parser.add_argument("--p-bpush-v", type=float, default=1.2)
    parser.add_argument("--p-bpush-kp", type=float, default=2.0)
    parser.add_argument("--p-bpush-max", type=float, default=0.0)
    parser.add_argument("--p-btrim-window", type=float, default=0.0)
    parser.add_argument("--p-btrim-v", type=float, default=2.5)
    parser.add_argument("--p-btrim-kp", type=float, default=0.0)
    parser.add_argument("--p-btrim-max", type=float, default=0.0)

    parser.add_argument("--m-ba", type=float, default=22.0)
    parser.add_argument("--m-send-ba", action="store_true")
    parser.add_argument("--m-bff", type=float, default=0.45)
    parser.add_argument("--m-bterm-x", type=float, default=0.6)
    parser.add_argument("--m-bterm-v", type=float, default=1.0)
    parser.add_argument("--m-bpush-window", type=float, default=1.8)
    parser.add_argument("--m-bpush-v", type=float, default=1.2)
    parser.add_argument("--m-bpush-kp", type=float, default=2.0)
    parser.add_argument("--m-bpush-max", type=float, default=0.0)
    parser.add_argument("--m-btrim-window", type=float, default=0.0)
    parser.add_argument("--m-btrim-v", type=float, default=2.5)
    parser.add_argument("--m-btrim-kp", type=float, default=0.0)
    parser.add_argument("--m-btrim-max", type=float, default=0.0)
    parser.add_argument("--btrim-slew", type=float, default=0.03)
    parser.add_argument("--btrim-deadband", type=float, default=0.15)
    parser.add_argument("--bbp-short-kp", type=float, default=0.35)
    parser.add_argument("--bbp-short-margin", type=float, default=2.0)
    parser.add_argument("--bbp-short-max", type=float, default=2.5)
    parser.add_argument("--bbp-short-dist", type=float, default=5.0)
    parser.add_argument("--bbp-long-kp", type=float, default=0.45)
    parser.add_argument("--bbp-long-margin", type=float, default=5.5)
    parser.add_argument("--bbp-long-max", type=float, default=4.0)
    parser.add_argument("--bbp-long-dist", type=float, default=10.0)
    parser.add_argument("--bbp-speed-kp", type=float, default=0.35)
    parser.add_argument("--bbp-speed-target-v", type=float, default=1.0)
    parser.add_argument("--bbp-speed-max", type=float, default=4.0)
    parser.add_argument("--bbp-negative-max", type=float, default=5.5,
                        help="optional direction-specific negative BBP max angle")

    parser.add_argument("--blimit", type=float, default=8.0)
    parser.add_argument("--bdead-x", type=float, default=0.25)
    parser.add_argument("--bdead-v", type=float, default=0.5)
    parser.add_argument("--brate", type=float, default=20.0)
    args = parser.parse_args()

    output = unique_output_path(args.output, args.overwrite)
    rows = []

    bff_command = f"bff2 {args.p_bff:g} {args.m_bff:g}" if args.device_seq else f"bff {args.p_bff:g}"
    if args.device_seq:
        setup_bterm_x = max(args.p_bterm_x, args.m_bterm_x)
        setup_bterm_v = max(args.p_bterm_v, args.m_bterm_v)
    else:
        setup_bterm_x = args.p_bterm_x
        setup_bterm_v = args.p_bterm_v
        setup_bpush_window = args.p_bpush_window
        setup_bpush_v = args.p_bpush_v
        setup_bpush_kp = args.p_bpush_kp
        setup_bpush_max = args.p_bpush_max
        setup_btrim_window = args.p_btrim_window
        setup_btrim_v = args.p_btrim_v
        setup_btrim_kp = args.p_btrim_kp
        setup_btrim_max = args.p_btrim_max
    plus_setup = [
        f"ba {args.p_ba:g}",
        bff_command,
        "bgain 0 0 0",
        f"bbp {args.bbp_short_kp:g} {args.bbp_short_margin:g} {args.bbp_short_max:g} {args.bbp_short_dist:g}",
        f"bbpd {args.bbp_long_kp:g} {args.bbp_long_margin:g} {args.bbp_long_max:g} {args.bbp_long_dist:g}",
        f"bbpv {args.bbp_speed_kp:g} {args.bbp_speed_target_v:g} {args.bbp_speed_max:g}",
        f"bterm {setup_bterm_x:g} {setup_bterm_v:g}",
        (f"bpushp {args.p_bpush_window:g} {args.p_bpush_v:g} {args.p_bpush_kp:g}"
         if args.device_seq else
         f"bpush {args.p_bpush_window:g} {args.p_bpush_v:g} {args.p_bpush_kp:g}"),
        (f"bpushm {args.m_bpush_window:g} {args.m_bpush_v:g} {args.m_bpush_kp:g}"
         if args.device_seq else
         f"btrim {args.p_btrim_window:g} {args.p_btrim_v:g} {args.p_btrim_kp:g} {args.p_btrim_max:g}"),
        f"blimit {args.blimit:g}",
        f"bdead {args.bdead_x:g} {args.bdead_v:g}",
        f"brate {args.brate:g}",
    ]
    if args.bbp_negative_max >= 0.0:
        plus_setup.insert(7, f"bbpn {args.bbp_negative_max:g}")
    minus_setup = [
        "bgain 0 0 0",
        f"bbp {args.bbp_short_kp:g} {args.bbp_short_margin:g} {args.bbp_short_max:g} {args.bbp_short_dist:g}",
        f"bbpd {args.bbp_long_kp:g} {args.bbp_long_margin:g} {args.bbp_long_max:g} {args.bbp_long_dist:g}",
        f"bterm {args.m_bterm_x:g} {args.m_bterm_v:g}",
        f"bpush {args.m_bpush_window:g} {args.m_bpush_v:g} {args.m_bpush_kp:g} {args.m_bpush_max:g}",
        f"btrim {args.m_btrim_window:g} {args.m_btrim_v:g} {args.m_btrim_kp:g} {args.m_btrim_max:g}",
        f"btrimlim {args.btrim_slew:g} {args.btrim_deadband:g}",
        f"blimit {args.blimit:g}",
        f"bdead {args.bdead_x:g} {args.bdead_v:g}",
        f"brate {args.brate:g}",
        f"bff {args.m_bff:g}",
    ]
    if args.m_send_ba:
        minus_setup.insert(0, f"ba {args.m_ba:g}")

    print(f"open {args.port} @ {args.baudrate} -> {output}", flush=True)
    with serial.Serial(args.port, args.baudrate, timeout=0.2) as ser, output.open(
        "w", encoding="utf-8", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()

        print("send +5 setup commands:", flush=True)
        send_commands(ser, plus_setup, args.command_delay_s)
        wait_gate(
            ser,
            "start",
            args.start_x,
            args.start_x_tol,
            args.start_v_tol,
            args.start_angle,
            args.start_angle_tol,
            args.start_stable_s,
            args.start_timeout_s,
            args.print_ms,
        )

        start_time = time.monotonic()
        if args.device_seq:
            print("command: > ball on", flush=True)
            ser.write(b"ball on\r\n")
            ser.flush()
            time.sleep(0.05)
            seq_cmd = f"bseq 5 -5 {args.seq_turn_window:g} {args.seq_turn_v:g}"
            print(f"command: > {seq_cmd}", flush=True)
            ser.write((seq_cmd + "\r\n").encode("utf-8"))
            ser.flush()
            capture_device_sequence(ser, writer, rows, start_time, args.seq_capture_s, args.print_ms)
            print(f"capture_done samples={len(rows)} output={output}", flush=True)
            return

        send_step_command(
            ser,
            5.0,
            args.p_ba + args.p_bff * 5.0,
            args.bt_retries,
            args.bt_retry_s,
        )

        if args.plus_use_turn_gate:
            wait_target_turn_gate(
                ser,
                writer,
                rows,
                start_time,
                "plus5",
                5.0,
                args.plus_turn_window,
                args.plus_turn_v_tol,
                args.plus_turn_hold_s,
                args.plus_timeout_s,
                args.print_ms,
            )
        else:
            wait_x_band_settle(
                ser,
                writer,
                rows,
                start_time,
                "plus5",
                args.plus_settle_min_x,
                args.plus_settle_max_x,
                args.plus_settle_x_eps,
                args.plus_settle_v_tol,
                args.plus_settle_hold_s,
                args.plus_timeout_s,
                args.print_ms,
            )

        print("send -5 transition setup commands:", flush=True)
        send_commands(ser, minus_setup, args.transition_command_delay_s)
        send_step_command(
            ser,
            -5.0,
            args.m_ba + args.m_bff * -5.0,
            args.bt_retries,
            args.bt_retry_s,
        )

        capture_for(ser, writer, rows, start_time, "minus5", args.minus_capture_s, args.print_ms)

    print(f"capture_done samples={len(rows)} output={output}", flush=True)


if __name__ == "__main__":
    main()
