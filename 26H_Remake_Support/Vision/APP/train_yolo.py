#!/usr/bin/env python3
"""Fine-tune a one-class YOLO detector for 640x128 steel-ball ROI images."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys


SUPPORT_ROOT = Path(__file__).resolve().parents[2]
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from Vision.Config.paths import (  # noqa: E402
    LAST_MODEL,
    MODEL_DIR,
    MODEL_RUNS_DIR,
    TRAINED_MODEL,
    WORKSPACE_ROOT,
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
        description="Windows上微调640x128钢球ROI专用YOLO检测模型"
    )
    add_config_argument(parser)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--batch", type=int)
    parser.add_argument(
        "--imgsz",
        type=int,
        help="训练API使用最长边整数；rect=True会保持640x128矩形批次",
    )
    parser.add_argument(
        "--device",
        help="auto、cpu、0或0,1；默认优先使用CUDA GPU",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Windows默认0，避免DataLoader多进程问题",
    )
    parser.add_argument("--patience", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--name")
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="从指定last.pt恢复训练",
    )
    parser.add_argument(
        "--cache",
        choices=("ram", "disk", "none"),
    )
    return parser


def resolve_device(requested: str, torch_module) -> str:
    if requested != "auto":
        return requested
    return "0" if torch_module.cuda.is_available() else "cpu"


def validate_args(args: argparse.Namespace) -> None:
    if args.epochs <= 0:
        raise ValueError("--epochs必须为正数")
    if args.batch == 0:
        raise ValueError("--batch不能为0")
    if args.imgsz < 32 or args.imgsz % 32:
        raise ValueError("--imgsz必须是正的32倍数")
    if args.workers < 0:
        raise ValueError("--workers不能为负数")
    if args.patience < 0:
        raise ValueError("--patience不能为负数")
    if not args.name or any(character in args.name for character in '<>:"/\\|?*'):
        raise ValueError("--name不能为空或包含Windows文件名非法字符")


def run(args: argparse.Namespace) -> Path:
    validate_args(args)
    data_path = args.data.expanduser().resolve()
    if not data_path.is_file():
        raise FileNotFoundError(
            f"找不到数据配置：{data_path}；请先运行prepare_dataset.py"
        )
    manifest_path = data_path.parent / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"数据集缺少几何清单：{manifest_path}")
    try:
        dataset_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        image_geometry = dataset_manifest["image_size"]
        dataset_width = int(image_geometry["width"])
        dataset_height = int(image_geometry["height"])
        geometry_id = str(dataset_manifest["geometry_id"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"数据集几何清单无效：{manifest_path}") from exc
    if (dataset_width, dataset_height) != (640, 128):
        raise ValueError(
            f"当前训练要求640x128，数据集实际为"
            f"{dataset_width}x{dataset_height}"
        )
    if len(geometry_id) != 64:
        raise ValueError("数据集geometry_id无效")

    try:
        import torch
        import ultralytics
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "训练依赖未安装，请在train目录运行："
            "python -m pip install -r requirements.txt"
        ) from exc

    resume_path = (
        None
        if args.resume_from is None
        else args.resume_from.expanduser().resolve()
    )
    if resume_path is not None:
        if not resume_path.is_file():
            raise FileNotFoundError(f"找不到恢复检查点：{resume_path}")
        model_path = resume_path
    else:
        model_path = args.model.expanduser().resolve()
        if not model_path.is_file():
            raise FileNotFoundError(f"找不到预训练模型：{model_path}")

    device = resolve_device(args.device, torch)
    cache: str | bool = False if args.cache == "none" else args.cache
    print(
        f"Ultralytics={ultralytics.__version__}; "
        f"PyTorch={torch.__version__}; device={device}",
        flush=True,
    )
    if device == "cpu":
        print(
            "WARNING: 当前使用CPU训练；若电脑有NVIDIA显卡，请安装匹配CUDA的PyTorch。",
            flush=True,
        )
    print(
        "Training geometry: source=640x128, imgsz=640, rect=True; "
        "Mosaic/MixUp disabled.",
        flush=True,
    )

    model = YOLO(str(model_path), task="detect")
    model.train(
        data=str(data_path),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=device,
        workers=args.workers,
        patience=args.patience,
        project=str(args.project.expanduser().resolve()),
        name=args.name,
        seed=args.seed,
        deterministic=True,
        single_cls=True,
        rect=True,
        cache=cache,
        optimizer="auto",
        amp=True,
        val=True,
        plots=True,
        save=True,
        save_period=-1,
        resume=resume_path is not None,
        # The installed system always has one ball and a fixed rectified rod.
        # Mosaic and MixUp would create physically impossible multi-ball ROIs.
        mosaic=0.0,
        mixup=0.0,
        copy_paste=0.0,
        close_mosaic=0,
        degrees=0.0,
        translate=0.04,
        scale=0.12,
        shear=0.0,
        perspective=0.0,
        flipud=0.0,
        fliplr=0.5,
        hsv_h=0.015,
        hsv_s=0.25,
        hsv_v=0.25,
    )
    trainer = model.trainer
    if trainer is None:
        raise RuntimeError("Ultralytics训练结束后没有返回trainer")
    best_path = Path(str(trainer.best)).resolve()
    if not best_path.is_file():
        raise RuntimeError(f"训练结束但找不到best.pt：{best_path}")

    save_dir = Path(str(trainer.save_dir)).resolve()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best_path, TRAINED_MODEL)
    last_path = Path(str(trainer.last)).resolve()
    if last_path.is_file():
        shutil.copy2(last_path, LAST_MODEL)
    model_geometry = {
        "schema": "steel-ball-model-geometry/v1",
        "geometry_id": geometry_id,
        "input_height": dataset_height,
        "input_width": dataset_width,
        "dataset_manifest": str(manifest_path),
    }
    for published in (TRAINED_MODEL, LAST_MODEL):
        if published.is_file():
            published.with_suffix(published.suffix + ".geometry.json").write_text(
                json.dumps(model_geometry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    summary = {
        "schema": "steel-ball-roi-training-run/v1",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "ultralytics_version": ultralytics.__version__,
        "torch_version": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "device": str(device),
        "data": str(data_path),
        "initial_model": str(model_path),
        "best_model": str(best_path),
        "last_model": str(last_path),
        "published_best_model": str(TRAINED_MODEL),
        "published_last_model": (
            str(LAST_MODEL) if last_path.is_file() else None
        ),
        "image_geometry": {
            "dataset_width": dataset_width,
            "dataset_height": dataset_height,
            "geometry_id": geometry_id,
            "training_imgsz": args.imgsz,
            "rectangular_batches": True,
        },
        "epochs_requested": args.epochs,
        "batch": args.batch,
        "seed": args.seed,
    }
    (save_dir / "roi_training_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Best model: {best_path}", flush=True)
    print(f"Published short path: {TRAINED_MODEL}", flush=True)
    return TRAINED_MODEL


def main() -> int:
    configure_windows_console()
    parser = build_parser()
    args = parse_args_with_config(parser, sections=("training",))
    try:
        run(args)
        return 0
    except (
        FileNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"Training failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
