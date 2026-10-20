#!/usr/bin/env python3
"""Import reviewed ball/negative labels into an existing capture session."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
import sys


SUPPORT_ROOT = Path(__file__).resolve().parents[2]
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from Vision.Core.dataset import RoiDatasetWriter  # noqa: E402


FIELDS = ("sample_id", "label_state", "cx", "cy", "w", "h")


def configure_windows_console() -> None:
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")


def load_manifest(path: Path) -> dict[str, tuple[str, tuple[float, ...] | None]]:
    entries: dict[str, tuple[str, tuple[float, ...] | None]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise ValueError(f"清单表头必须是：{','.join(FIELDS)}")
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"第{line_number}行列数不正确")
            sample_id = row["sample_id"].strip()
            state = row["label_state"].strip().lower()
            if not sample_id or sample_id in entries:
                raise ValueError(f"第{line_number}行样本编号为空或重复：{sample_id}")
            if state not in ("positive", "negative"):
                raise ValueError(f"第{line_number}行状态只能是positive或negative")
            raw_box = tuple(row[field].strip() for field in FIELDS[2:])
            if state == "negative":
                if any(raw_box):
                    raise ValueError(f"第{line_number}行负样本不能有框")
                box = None
            else:
                try:
                    box = tuple(float(value) for value in raw_box)
                except ValueError as exc:
                    raise ValueError(f"第{line_number}行有球样本缺少有效框") from exc
                if not all(math.isfinite(value) for value in box):
                    raise ValueError(f"第{line_number}行框必须是有限数值")
                cx, cy, width, height = box
                if (
                    not (0 < width <= 1 and 0 < height <= 1)
                    or cx - width / 2 < 0
                    or cy - height / 2 < 0
                    or cx + width / 2 > 1
                    or cy + height / 2 > 1
                ):
                    raise ValueError(f"第{line_number}行YOLO框超出图像或尺寸无效")
            entries[sample_id] = (state, box)
    if not entries:
        raise ValueError("清单没有样本")
    return entries


def run(session_dir: Path, manifest: Path, *, apply: bool) -> dict[str, int]:
    session_dir = session_dir.expanduser().resolve()
    if not (session_dir / "session.json").is_file() or not (session_dir / "metadata.jsonl").is_file():
        raise FileNotFoundError(f"不是完整采集会话：{session_dir}")
    entries = load_manifest(manifest.expanduser().resolve())
    writer = RoiDatasetWriter(session_dir, append_existing=True)
    unlabeled = {sample.sample_id for sample in writer.unlabeled_samples}
    if set(entries) != unlabeled:
        missing = sorted(unlabeled - set(entries))
        unexpected = sorted(set(entries) - unlabeled)
        raise ValueError(
            f"清单必须覆盖全部待标注样本；遗漏={missing[:8]} "
            f"多余/已标注={unexpected[:8]}"
        )
    for sample_id in entries:
        if not (session_dir / "unlabeled" / f"{sample_id}.png").is_file():
            raise FileNotFoundError(f"待标注图片不存在：{sample_id}")
    counts = {
        "positive": sum(state == "positive" for state, _ in entries.values()),
        "negative": sum(state == "negative" for state, _ in entries.values()),
    }
    if apply:
        for sample_id, (state, box) in entries.items():
            writer.label_unlabeled(sample_id, label_state=state, yolo_box=box)
    return counts


def main() -> int:
    configure_windows_console()
    parser = argparse.ArgumentParser(description="导入已复核的球框/负样本清单")
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只校验")
    args = parser.parse_args()
    try:
        counts = run(args.session_dir, args.manifest, apply=args.apply)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Annotation import failed: {exc}", file=sys.stderr)
        return 1
    action = "Imported" if args.apply else "Validated (dry run)"
    print(f"{action}: {counts['positive']} positive, {counts['negative']} negative")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
