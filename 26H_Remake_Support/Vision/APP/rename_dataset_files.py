#!/usr/bin/env python3
"""Rename copied calibration and training assets without touching runtime code.

The default mode is a dry run. Use --apply to perform the rename. Original
capture records under source_records are deliberately kept immutable; the
generated CSV manifest maps every original path to its descriptive new path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = PROJECT_ROOT / "Data" / "Training" / "steel_ball_12_30deg_exp10" / "by_angle"
CALIBRATION_ROOT = (
    PROJECT_ROOT
    / "Data"
    / "Calibration"
    / "angle_12_30deg"
)
MANIFEST_PATH = PROJECT_ROOT / "VISUAL_ASSET_RENAME_MANIFEST.csv"
CHECKSUM_PATH = PROJECT_ROOT / "SHA256SUMS.txt"

ANGLE_DIR_PATTERN = re.compile(r"angle_(\d+)deg_exp(\d+)$")
TRAINING_FILE_PATTERN = re.compile(r"roi_(\d+)\.(png|txt)$", re.IGNORECASE)
CALIBRATION_FILE_PATTERN = re.compile(
    r"manual_\d+_p(\d+(?:\.\d+)?)_(source|rectified)\.png$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RenameOperation:
    category: str
    source: Path
    destination: Path


def relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_angle(value: str) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number).replace(".", "p")


def collect_training_operations() -> list[RenameOperation]:
    operations: list[RenameOperation] = []
    for angle_dir in sorted(DATASET_ROOT.iterdir()):
        match = ANGLE_DIR_PATTERN.fullmatch(angle_dir.name)
        if not angle_dir.is_dir() or match is None:
            continue
        angle, exposure = match.groups()
        for kind, extension in (("images", "png"), ("labels", "txt")):
            folder = angle_dir / kind
            for source in sorted(folder.glob(f"*.{extension}")):
                file_match = TRAINING_FILE_PATTERN.fullmatch(source.name)
                if file_match is None:
                    continue
                sample_id = file_match.group(1)
                new_name = (
                    f"steel_ball_angle_{int(angle):02d}deg_"
                    f"exposure_{int(exposure)}_{sample_id}.{extension}"
                )
                operations.append(
                    RenameOperation("training", source, source.with_name(new_name))
                )
    return operations


def collect_calibration_operations() -> list[RenameOperation]:
    operations: list[RenameOperation] = []
    for folder_name in ("source_images", "rectified_images"):
        folder = CALIBRATION_ROOT / folder_name
        for source in sorted(folder.glob("*.png")):
            match = CALIBRATION_FILE_PATTERN.fullmatch(source.name)
            if match is None:
                continue
            angle, image_kind = match.groups()
            new_name = f"calibration_angle_{normalized_angle(angle)}deg_{image_kind.lower()}.png"
            operations.append(
                RenameOperation("calibration", source, source.with_name(new_name))
            )
    return operations


def validate(operations: list[RenameOperation]) -> None:
    destinations = [item.destination for item in operations]
    if len(destinations) != len(set(destinations)):
        raise RuntimeError("Two source files would be renamed to the same destination")
    for item in operations:
        if not item.source.is_file():
            raise FileNotFoundError(item.source)
        if item.destination.exists() and item.destination != item.source:
            raise FileExistsError(item.destination)


def write_manifest(operations: list[RenameOperation]) -> None:
    if MANIFEST_PATH.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing rename manifest: {MANIFEST_PATH}"
        )
    with MANIFEST_PATH.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["category", "original_relative_path", "renamed_relative_path", "sha256"]
        )
        for item in operations:
            writer.writerow(
                [
                    item.category,
                    relative(item.source),
                    relative(item.destination),
                    sha256(item.source),
                ]
            )


def validate_training_pairs() -> None:
    images = sorted(DATASET_ROOT.rglob("images/*.png"))
    labels = sorted(DATASET_ROOT.rglob("labels/*.txt"))
    if len(images) != 2405 or len(labels) != 2405:
        raise RuntimeError(
            f"Unexpected training counts after rename: images={len(images)}, labels={len(labels)}"
        )
    for image in images:
        label = image.parent.parent / "labels" / f"{image.stem}.txt"
        if not label.is_file():
            raise RuntimeError(f"Missing paired label for {relative(image)}")


def rebuild_checksums() -> None:
    files = sorted(
        path
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file() and path != CHECKSUM_PATH
    )
    lines = [f"{sha256(path)}  {relative(path)}\n" for path in files]
    CHECKSUM_PATH.write_text("".join(lines), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely rename visual calibration and training assets."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the rename; without this option only a preview is printed",
    )
    args = parser.parse_args()

    operations = collect_calibration_operations() + collect_training_operations()
    validate(operations)
    calibration_count = sum(item.category == "calibration" for item in operations)
    training_count = sum(item.category == "training" for item in operations)

    print(f"project_root={PROJECT_ROOT}")
    print(f"calibration_files={calibration_count}")
    print(f"training_files={training_count}")
    print(f"total_renames={len(operations)}")
    for item in operations[:10]:
        print(f"{relative(item.source)} -> {relative(item.destination)}")
    if len(operations) > 10:
        print(f"... and {len(operations) - 10} more")

    if not args.apply:
        print("dry_run=true")
        return 0

    if not operations:
        print("No matching files require renaming.")
        return 0

    write_manifest(operations)
    for item in operations:
        item.source.rename(item.destination)
    validate_training_pairs()
    rebuild_checksums()
    print(f"manifest={MANIFEST_PATH}")
    print("rename_complete=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
