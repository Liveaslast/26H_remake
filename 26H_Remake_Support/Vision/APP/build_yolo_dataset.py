#!/usr/bin/env python3
"""Validate capture sessions and build a Windows YOLO training dataset."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys

import yaml

SUPPORT_ROOT = Path(__file__).resolve().parents[2]
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from Vision.Core.dataset_tools import (  # noqa: E402
    RoiDatasetItem,
    collect_session_items,
    reject_duplicate_images,
    split_items,
)
from Vision.Config.config import (  # noqa: E402
    add_config_argument,
    parse_args_with_config,
)


def configure_windows_console() -> None:
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验采集会话并整理640x128钢球ROI数据集"
    )
    add_config_argument(parser)
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        required=True,
        help="采集会话目录，可重复提供；目录内必须有images/和labels/",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--val-fraction", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--split-mode",
        choices=("image", "session"),
        help="单会话30张数据使用image；多个独立会话推荐session",
    )
    return parser


def copy_split(
    items: list[RoiDatasetItem],
    output_dir: Path,
    split: str,
) -> list[dict[str, object]]:
    images_dir = output_dir / "images" / split
    labels_dir = output_dir / "labels" / split
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, object]] = []
    used_names: set[str] = set()
    for item in items:
        stem = item.destination_stem
        if stem in used_names:
            raise ValueError(f"整理后的样本名重复：{stem}")
        used_names.add(stem)
        image_destination = images_dir / f"{stem}{item.image_path.suffix.lower()}"
        label_destination = labels_dir / f"{stem}.txt"
        if image_destination.exists() or label_destination.exists():
            raise FileExistsError(f"拒绝覆盖数据集样本：{stem}")
        shutil.copy2(item.image_path, image_destination)
        shutil.copy2(item.label_path, label_destination)
        manifest.append(
            {
                "split": split,
                "session": item.session_name,
                "source_image": str(item.image_path),
                "source_label": str(item.label_path),
                "image": image_destination.relative_to(output_dir).as_posix(),
                "label": label_destination.relative_to(output_dir).as_posix(),
                "objects": item.object_count,
                "sha256": item.sha256,
                "geometry_id": item.geometry_id,
            }
        )
    return manifest


def run(args: argparse.Namespace) -> Path:
    if min(args.width, args.height) < 32:
        raise ValueError("图片宽高必须至少为32")
    if args.width % 32 or args.height % 32:
        raise ValueError("图片宽高必须是32的倍数")
    if not 0 < args.val_fraction < 1:
        raise ValueError("--val-fraction必须在(0,1)内")

    output_dir = args.output_dir.expanduser().resolve()
    output_existed_before_run = output_dir.exists()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"输出目录已经存在且非空，拒绝覆盖：{output_dir}"
        )

    all_items: list[RoiDatasetItem] = []
    for source in args.source:
        items = collect_session_items(
            source,
            expected_size=(args.width, args.height),
        )
        print(
            f"Validated {source.resolve()}: {len(items)} images, "
            f"{sum(item.is_positive for item in items)} positive, "
            f"{sum(not item.is_positive for item in items)} negative",
            flush=True,
        )
        all_items.extend(items)

    if len(all_items) < 10:
        raise ValueError("至少需要10张已标注图片才能建立基本训练/验证集")
    if sum(item.is_positive for item in all_items) < 2:
        raise ValueError("至少需要2张有球图片")
    reject_duplicate_images(all_items)
    geometry_ids = {item.geometry_id for item in all_items}
    if len(geometry_ids) > 1:
        rendered = ", ".join(
            "legacy-missing" if value is None else value[:12]
            for value in sorted(geometry_ids, key=lambda item: str(item))
        )
        raise ValueError(f"数据集混入不同ROI几何：{rendered}")
    geometry_id = next(iter(geometry_ids))
    if (args.width, args.height) == (640, 128) and geometry_id is None:
        raise ValueError(
            "640x128新ROI数据必须由当前采集程序生成并包含geometry_id"
        )
    train, validation = split_items(
        all_items,
        validation_fraction=args.val_fraction,
        seed=args.seed,
        mode=args.split_mode,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        manifest = copy_split(train, output_dir, "train")
        manifest.extend(copy_split(validation, output_dir, "val"))
        config_path = output_dir / "roi_ball.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "path": output_dir.as_posix(),
                    "train": "images/train",
                    "val": "images/val",
                    "names": {0: "steel_ball"},
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        counts = Counter(
            (record["split"], "positive" if record["objects"] else "negative")
            for record in manifest
        )
        summary = {
            "schema": "steel-ball-roi-training-dataset/v1",
            "image_size": {"width": args.width, "height": args.height},
            "geometry_id": geometry_id,
            "split_mode": args.split_mode,
            "validation_fraction": args.val_fraction,
            "seed": args.seed,
            "source_sessions": [
                str(path.expanduser().resolve()) for path in args.source
            ],
            "counts": {
                "total": len(manifest),
                "train": len(train),
                "val": len(validation),
                "train_positive": counts[("train", "positive")],
                "train_negative": counts[("train", "negative")],
                "val_positive": counts[("val", "positive")],
                "val_negative": counts[("val", "negative")],
            },
            "samples": manifest,
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        # Only remove a directory created by this run. A pre-existing empty
        # directory belongs to the operator and is left intact.
        if not output_existed_before_run:
            shutil.rmtree(output_dir, ignore_errors=True)
        raise

    print(json.dumps(summary["counts"], ensure_ascii=False), flush=True)
    print(f"Dataset ready: {config_path}", flush=True)
    return config_path


def main() -> int:
    configure_windows_console()
    parser = build_parser()
    args = parse_args_with_config(parser, sections=("dataset_prepare",))
    try:
        run(args)
        return 0
    except (FileExistsError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Dataset preparation failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
