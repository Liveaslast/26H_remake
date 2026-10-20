"""Sample seven positions per angle and make independent image-only trial boxes."""

import csv
from pathlib import Path
import shutil

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "steel_ball_12_30deg_exp10" / "by_angle"
IMAGE_SIZE = (640, 128)


def load_yolo(path):
    rows = path.read_text().strip().splitlines()
    if len(rows) != 1:
        return None
    parts = rows[0].split()
    if len(parts) != 5 or parts[0] != "0":
        return None
    return tuple(map(float, parts[1:]))


def choose_frames(angle_dir):
    candidates = []
    for image_path in sorted((angle_dir / "images").glob("*.png")):
        old = load_yolo(angle_dir / "labels" / f"{image_path.stem}.txt")
        if old is not None:
            candidates.append((image_path, old))
    candidates.sort(key=lambda item: item[1][0])
    low, high = candidates[0][1][0], candidates[-1][1][0]
    targets = np.linspace(low, high, 7)
    selected = []
    remaining = candidates.copy()
    for target in targets:
        best = min(remaining, key=lambda item: abs(item[1][0] - target))
        selected.append(best)
        remaining.remove(best)
    return sorted(selected, key=lambda item: item[1][0])


def detect_ball(image):
    """Locate the dark steel-ball body from pixels alone, without label hints."""
    gray = np.asarray(image.convert("L"), dtype=np.int16)
    darkness = np.maximum(105 - gray[29:85, :], 0).sum(axis=0)
    score = np.convolve(darkness, np.ones(5) / 5, mode="same")
    peak = int(np.argmax(score[18:622]) + 18)
    x1, x2 = max(0, peak - 20), min(640, peak + 21)
    patch = gray[16:94, x1:x2]
    dark = patch < 95
    columns = dark[14:71].sum(axis=0)
    rows = dark.sum(axis=1)
    xs = np.flatnonzero(columns >= 9)
    ys = np.flatnonzero(rows >= 3)
    if len(xs) < 4 or len(ys) < 20:
        raise ValueError(f"Ball not resolved near column {peak}")
    left = max(0, x1 + int(xs.min()) - 5)
    right = min(640, x1 + int(xs.max()) + 6)
    top = max(0, 16 + int(ys.min()) + 2)
    bottom = min(128, 16 + int(ys.max()) + 3)
    return (left, top, right, bottom)


def to_yolo(edges):
    left, top, right, bottom = edges
    return ((left + right) / (2 * 640), (top + bottom) / (2 * 128),
            (right - left) / 640, (bottom - top) / 128)


def to_edges(yolo):
    x, y, width, height = yolo
    return ((x - width / 2) * 640, (y - height / 2) * 128,
            (x + width / 2) * 640, (y + height / 2) * 128)


def iou(a, b):
    al, at, ar, ab = a
    bl, bt, br, bb = b
    overlap = max(0, min(ar, br) - max(al, bl)) * max(0, min(ab, bb) - max(at, bt))
    return overlap / ((ar - al) * (ab - at) + (br - bl) * (bb - bt) - overlap)


def main():
    rows = []
    font = ImageFont.load_default()
    for angle_dir in sorted(SOURCE.glob("angle_*deg_exp10")):
        angle = angle_dir.name.split("_")[1].removesuffix("deg")
        panels = []
        comparison_panels = []
        for rank, (image_path, old) in enumerate(choose_frames(angle_dir), 1):
            name = f"angle_{angle}_{image_path.stem}"
            image = Image.open(image_path).convert("RGB")
            if image.size != IMAGE_SIZE:
                raise ValueError(f"Unexpected image size: {image_path}")
            new_edges = detect_ball(image)
            new = to_yolo(new_edges)
            (ROOT / "images").mkdir(exist_ok=True)
            (ROOT / "labels").mkdir(exist_ok=True)
            (ROOT / "previews").mkdir(exist_ok=True)
            shutil.copy2(image_path, ROOT / "images" / f"{name}.png")
            (ROOT / "labels" / f"{name}.txt").write_text(
                "0 " + " ".join(f"{value:.8f}" for value in new) + "\n"
            )
            panel = image.copy()
            draw = ImageDraw.Draw(panel)
            draw.rectangle(new_edges, outline=(255, 45, 35), width=2)
            draw.text((4, 3), f"{angle}deg  {rank}/7  {image_path.stem}",
                      fill=(255, 45, 35), font=font)
            panel.save(ROOT / "previews" / f"{name}.png")
            panels.append(panel)
            old_edges = to_edges(old)
            comparison = image.copy()
            comparison_draw = ImageDraw.Draw(comparison)
            comparison_draw.rectangle(old_edges, outline=(30, 120, 255), width=2)
            comparison_draw.rectangle(new_edges, outline=(255, 45, 35), width=2)
            comparison_draw.text((4, 3), f"{angle}deg  {rank}/7  {image_path.stem}",
                                 fill=(255, 45, 35), font=font)
            (ROOT / "comparison_previews").mkdir(exist_ok=True)
            comparison.save(ROOT / "comparison_previews" / f"{name}.png")
            comparison_panels.append(comparison)
            dx = (new[0] - old[0]) * 640
            dy = (new[1] - old[1]) * 128
            rows.append({"angle_deg": angle, "rank": rank, "image": name,
                         "old_center_x_px": old[0] * 640,
                         "new_center_x_px": new[0] * 640,
                         "dx_px": dx, "dy_px": dy,
                         "center_error_px": float(np.hypot(dx, dy)),
                         "iou": iou(new_edges, old_edges)})
        sheet = Image.new("RGB", (640, 128 * len(panels)))
        for index, panel in enumerate(panels):
            sheet.paste(panel, (0, 128 * index))
        (ROOT / "contact_sheets").mkdir(exist_ok=True)
        sheet.save(ROOT / "contact_sheets" / f"angle_{angle}.png")
        comparison_sheet = Image.new("RGB", (640, 128 * len(comparison_panels)))
        for index, panel in enumerate(comparison_panels):
            comparison_sheet.paste(panel, (0, 128 * index))
        (ROOT / "comparison_sheets").mkdir(exist_ok=True)
        comparison_sheet.save(ROOT / "comparison_sheets" / f"angle_{angle}.png")
    with (ROOT / "comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Generated {len(rows)} boxes in {ROOT}")
    for angle in sorted({row["angle_deg"] for row in rows}, key=int):
        group = [row for row in rows if row["angle_deg"] == angle]
        print(f"{angle:>2}deg: center={np.mean([r['center_error_px'] for r in group]):.2f}px, "
              f"IoU={np.mean([r['iou'] for r in group]):.3f}")
    print(f"ALL: center={np.mean([r['center_error_px'] for r in rows]):.2f}px, "
          f"IoU={np.mean([r['iou'] for r in rows]):.3f}")


if __name__ == "__main__":
    main()
