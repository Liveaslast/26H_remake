from math import hypot
from pathlib import Path


trial = Path(__file__).resolve().parent
source = trial.parent / "steel_ball_12_30deg_exp10" / "by_angle"


def read_box(path):
    return tuple(map(float, path.read_text().split()[1:]))


def edges(box):
    x, y, width, height = box
    return (x - width / 2, y - height / 2, x + width / 2, y + height / 2)


def iou(a, b):
    ax1, ay1, ax2, ay2 = edges(a)
    bx1, by1, bx2, by2 = edges(b)
    overlap = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return overlap / (area_a + area_b - overlap)


rows = []
for label in sorted((trial / "labels").glob("*.txt")):
    angle, frame = label.stem.split("_roi_")
    original = source / f"{angle}deg_exp10" / "labels" / f"roi_{frame}.txt"
    new_box = read_box(label)
    old_box = read_box(original)
    center_error = hypot((new_box[0] - old_box[0]) * 640, (new_box[1] - old_box[1]) * 128)
    overlap = iou(new_box, old_box)
    rows.append((label.stem, center_error, overlap))
    print(f"{label.stem}: center={center_error:.1f}px, IoU={overlap:.3f}")

print(f"Mean: center={sum(row[1] for row in rows) / len(rows):.1f}px, "
      f"IoU={sum(row[2] for row in rows) / len(rows):.3f}")
