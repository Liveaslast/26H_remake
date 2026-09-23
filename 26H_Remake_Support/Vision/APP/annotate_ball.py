#!/usr/bin/env python3
"""Batch-label pruned rolling-capture ROI sessions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

# The OpenCV PyPI wheel on Raspberry Pi contains xcb, while WayVNC may make Qt
# choose the unavailable wayland plugin.
if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    if Path("/usr/share/fonts/truetype/dejavu").is_dir():
        os.environ.setdefault(
            "QT_QPA_FONTDIR",
            "/usr/share/fonts/truetype/dejavu",
        )


SUPPORT_ROOT = Path(__file__).resolve().parents[2]
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from Vision.Core.dataset import RoiDatasetWriter  # noqa: E402
from Vision.APP.capture_training_data import annotate_unlabeled_queue  # noqa: E402


DEFAULT_DATASET_ROOT = (
    SUPPORT_ROOT / "Data" / "Training" / "steel_ball_12_30deg_exp10"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Open every selected roll_angle session and label its remaining "
            "unlabeled ROI images."
        )
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="ROI dataset root; default: Data/Training/steel_ball_12_30deg_exp10",
    )
    parser.add_argument(
        "--pattern",
        default="roll_angle*_??",
        help="Session directory glob pattern; default: roll_angle*_??",
    )
    parser.add_argument(
        "--annotation-scale",
        type=float,
        default=6.0,
        help="Display scale for drawing ball boxes; default: 6.0",
    )
    return parser


def load_records(metadata_path: Path) -> list[dict]:
    records: list[dict] = []
    for line in metadata_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def load_writer(session_dir: Path) -> RoiDatasetWriter:
    metadata_path = session_dir / "metadata.jsonl"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"metadata.jsonl not found: {metadata_path}")

    writer = RoiDatasetWriter.__new__(RoiDatasetWriter)
    writer.session_dir = session_dir.resolve()
    writer.prefix = "roi"
    writer.save_source = False
    writer.source_jpeg_quality = 95
    writer.png_compression = 0
    writer._records = load_records(metadata_path)
    writer._next_index = (
        max((int(record.get("index", 0)) for record in writer._records), default=0)
        + 1
    )
    return writer


def session_has_unlabeled(session_dir: Path) -> bool:
    folder = session_dir / "unlabeled"
    return folder.is_dir() and any(folder.glob("roi_*.png"))


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.annotation_scale < 1:
        parser.error("--annotation-scale must be at least 1")

    dataset_root = args.dataset_root.expanduser().resolve()
    if not dataset_root.is_dir():
        raise SystemExit(f"dataset root not found: {dataset_root}")

    sessions = sorted(
        path
        for path in dataset_root.glob(args.pattern)
        if path.is_dir() and session_has_unlabeled(path)
    )
    if not sessions:
        print("No unlabeled roll_angle sessions found.", flush=True)
        return 0

    print(
        f"Found {len(sessions)} sessions. "
        "1=框球，2=确认，N=无球，Space/S=跳过，X=上一步，Q=进入下一组/退出当前组。",
        flush=True,
    )
    for index, session_dir in enumerate(sessions, start=1):
        print(
            f"\nSession {index}/{len(sessions)}: {session_dir.name}",
            flush=True,
        )
        writer = load_writer(session_dir)
        annotate_unlabeled_queue(writer, args.annotation_scale)

    print("Batch labeling finished.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
