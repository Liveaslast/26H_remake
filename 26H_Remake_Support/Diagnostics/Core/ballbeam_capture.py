"""USART6 Task1采集：解析当前7列控制数据，记录固定任务序列。"""

import time
from pathlib import Path

CHANNELS = ["ab_x", "target_x", "ab_v", "angle", "target_angle", "seq_stage", "age_ms"]
HEADER = ["t_s", "phase"] + CHANNELS


def parse_line(line):
    parts = line.strip().split(",")
    if len(parts) != len(CHANNELS):
        return None
    try:
        values = [int(part) for part in parts]
    except ValueError:
        return None
    values = [value / 100.0 for value in values[:5]] + values[5:]
    return dict(zip(CHANNELS, values))


def unique_output_path(path, overwrite=False):
    path = Path(path)
    if overwrite or not path.exists():
        return path
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.stem}_{stamp}{path.suffix}")


def read_valid_sample(ser):
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        vals = parse_line(line)
        if vals is not None:
            return vals


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
                f"seq={int(vals['seq_stage'])} "
                f"age={vals['age_ms']:4.0f}",
                flush=True,
            )
