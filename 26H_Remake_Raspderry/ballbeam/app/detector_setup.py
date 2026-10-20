"""Load and validate Hailo/NCNN detector deployments and model input sizes.

检测器：输入图片，根据模型输出小球数据
    1.根据配置选择 HailoRT、Hailo 或 NCNN 推理后端
    2.检查模型路径、输入尺寸及模型与视觉标定的匹配关系
    3.创建检测器，并按配置进行预热
    4.返回检测器，供跟踪程序调用
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

from ..errors import RuntimeIOError


def resolve_inference_image_size(
    model_path: Path,
    requested_size: int,
) -> int | tuple[int, int]:
    """读取NCNN导出尺寸；返回整数或``(height, width)``。"""

    requested = int(requested_size)
    exported: int | tuple[int, int] | None = None
    metadata_path = model_path / "metadata.yaml"
    if model_path.is_dir() and metadata_path.is_file():
        try:
            import yaml

            metadata = yaml.safe_load(
                metadata_path.read_text(encoding="utf-8")
            )
            raw_size = metadata.get("imgsz") if isinstance(metadata, dict) else None
            if isinstance(raw_size, (list, tuple)):
                values = [int(value) for value in raw_size]
                if len(values) != 2:
                    raise RuntimeIOError(
                        f"模型元数据中的 imgsz 必须包含高和宽：{raw_size!r}"
                    )
                exported = (
                    values[0]
                    if values[0] == values[1]
                    else (values[0], values[1])
                )
            elif raw_size is not None:
                exported = int(raw_size)
        except RuntimeIOError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeIOError(
                f"无法解析模型输入尺寸：{metadata_path}"
            ) from exc
        dimensions = (
            ()
            if exported is None
            else exported
            if isinstance(exported, tuple)
            else (exported,)
        )
        if (
            not dimensions
            or any(
                dimension <= 0 or dimension % 32 != 0
                for dimension in dimensions
            )
        ):
            raise RuntimeIOError(
                f"模型元数据中的 imgsz 无效：{metadata_path}"
            )

    if exported is not None:
        if isinstance(exported, tuple):
            if requested != 0:
                raise RuntimeIOError(
                    f"NCNN模型是固定 {exported[0]}x{exported[1]} "
                    "矩形输入；请省略 --image-size，让程序自动读取模型元数据"
                )
            return exported
        if requested not in (0, exported):
            raise RuntimeIOError(
                f"NCNN模型是静态 {exported}x{exported} 输入，"
                f"不能使用 --image-size {requested}；请省略该参数或使用 "
                f"--image-size {exported}"
            )
        return exported
    if requested == 0:
        return 512
    return requested


def resolve_model(args, inference_backend):
    """Resolve model location and verify its declared input dimensions."""
    if inference_backend in ("hailo", "hailort"):
        if args.hailo_model is None:
            raise RuntimeIOError(
                "Hailo后端需要指定 --hailo-model，例如 "
                "assets/models/hailo"
            )
        model_path = args.hailo_model.expanduser().resolve()
    else:
        model_path = args.model.expanduser().resolve()
    if not model_path.is_dir():
        raise RuntimeIOError(
            f"{inference_backend.upper()} 模型目录不存在：{model_path}。"
        )
    if inference_backend in ("hailo", "hailort"):
        image_size = (
            int(args.model_height),
            int(args.model_width),
        ) if int(args.image_size) == 0 else args.image_size
    else:
        image_size = resolve_inference_image_size(
            model_path,
            args.image_size,
        )
    resolved_size = (
        (image_size, image_size)
        if isinstance(image_size, int)
        else image_size
    )
    expected_size = (int(args.model_height), int(args.model_width))
    if resolved_size != expected_size:
        raise RuntimeIOError(
            f"{inference_backend.upper()}模型输入为{resolved_size[0]}x{resolved_size[1]}，"
            f"当前ROI方案要求{expected_size[0]}x{expected_size[1]}；"
            "请使用新数据重新训练和导出模型"
        )
    return model_path, image_size


def validate_model_geometry(model_path, inference_backend, calibration_geometry_id,
                            *, allow_historical=False):
    """Validate deployment provenance independently of detector construction."""
    deployment_path = model_path / "deployment.json"
    if deployment_path.is_file():
        try:
            deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
            model_geometry_id = str(deployment["geometry_id"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeIOError(
                f"模型缺少有效geometry_id：{deployment_path}；"
                "请用当前导出脚本重新生成模型"
            ) from exc
        if model_geometry_id != calibration_geometry_id:
            known_historical_pair = (
                inference_backend == "ncnn"
                and model_geometry_id
                == "b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad"
                and calibration_geometry_id
                == "8a5cd731dad6021704fb36f25fd423fa7ecd1634c998e23d7eaf9b13ff81126f"
            )
            if not (
                known_historical_pair
                and allow_historical
            ):
                raise RuntimeIOError(
                    f"模型geometry_id={model_geometry_id[:12]} 与标定"
                    f"geometry_id={calibration_geometry_id[:12]} 不一致"
                )
            print(
                "WARNING: 显式允许历史NCNN模型geometry_id="
                f"{model_geometry_id[:12]} 与当前标定geometry_id="
                f"{calibration_geometry_id[:12]} 不一致；仅供核对后的试验，"
                "先验证坐标再启动闭环控制。",
                file=sys.stderr,
                flush=True,
            )
    elif inference_backend == "ncnn":
        raise RuntimeIOError(
            f"NCNN模型缺少有效geometry_id：{deployment_path}；"
            "请用当前导出脚本重新生成模型"
        )
    else:
        print(
            f"WARNING: Hailo模型目录缺少deployment.json，无法自动校验geometry_id；"
            f"当前标定geometry_id={calibration_geometry_id[:12]}",
            file=sys.stderr,
            flush=True,
        )


def select_backend(inference_backend, requested_backend):
    """Resolve an available inference implementation without loading a model."""
    if inference_backend in ("hailo", "hailort"):
        return inference_backend
    from ..vision.detection_runtime.ncnn_backend import (
        native_ncnn_available, native_ncnn_import_error,
    )
    native_available = native_ncnn_available()
    if requested_backend == "cpp" and not native_available:
        detail = native_ncnn_import_error()
        raise RuntimeIOError(
            "The C++ NCNN extension is not built. Run "
            "the native NCNN extension on the "
            f"Raspberry Pi. Import error: {detail}"
        )
    else:
        use_native = requested_backend == "cpp" or (
            requested_backend == "auto" and native_available
        )
        backend_name = "cpp" if use_native else "ultralytics"
    if (
        inference_backend == "ncnn"
        and requested_backend == "auto"
        and not native_available
    ):
        print(
            "WARNING: C++ extension unavailable; using the accuracy-"
            "equivalent Python/Ultralytics fallback. Build it with "
            "the native NCNN extension.",
            file=sys.stderr,
            flush=True,
        )
    return backend_name


def create_legacy_detector(args, model_path, image_size):
    """Keep the existing Ultralytics fallback behind the same detector interface."""
    try:
        from ..vision.detection_common import BallDetector, BallDetectorConfig
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeIOError(
            "Unable to import ball_detection_common/Ultralytics. Install "
            "requirements.txt from the active virtual environment."
        ) from exc
    detector = BallDetector(
        BallDetectorConfig(
            model_path=model_path,
            image_size=image_size,
            confidence=args.confidence,
            iou_threshold=args.iou,
            class_id=0,
            max_detections=args.max_detections,
        ),
        model=YOLO(str(model_path), task="detect"),
    )
    return detector


def create_detector(args, model_path, image_size, inference_backend):
    """Assemble a detector from a backend and its algorithm configuration."""
    requested_backend = str(args.ncnn_backend).lower()
    try:
        from ..vision.detection_runtime.detector import (
            AdaptiveBallDetector, detector_config_for_mode,
        )
    except ImportError as exc:
        if inference_backend in ("hailo", "hailort"):
            raise RuntimeIOError("Hailo 检测模块导入失败；拒绝静默切换识别后端") from exc
        if requested_backend == "cpp":
            raise RuntimeIOError("C++ backend package is unavailable.") from exc
        print(f"WARNING: adaptive detector unavailable; using Ultralytics: {exc}",
              file=sys.stderr, flush=True)
        return create_legacy_detector(args, model_path, image_size), "ultralytics", "ultralytics-every-frame"

    backend_name = select_backend(inference_backend, requested_backend)
    speed_mode = str(args.speed_mode).lower()
    detection_interval = int(args.detection_interval)
    refine_interval = int(args.refine_interval)
    track_scale = float(args.track_scale)
    ncnn_threads = int(args.ncnn_threads)
    circle_backend = "python"
    overrides: dict[str, Any] = {
        "model_path": model_path,
        "image_size": image_size,
        "confidence": args.confidence,
        "iou_threshold": args.iou,
        "class_id": 0,
        "max_detections": args.max_detections,
        "detection_interval": detection_interval,
        "track_scale": track_scale,
        "ncnn_backend": backend_name,
        "ncnn_threads": ncnn_threads,
        "circle_backend": circle_backend,
        "enable_circle_refinement": not args.disable_circle_refinement,
    }
    if refine_interval > 0:
        overrides["refine_interval"] = refine_interval
    detector = AdaptiveBallDetector(
        detector_config_for_mode(speed_mode, **overrides)
    )
    detector_mode = (
        f"{speed_mode}; detect-every={detection_interval}; "
        f"track-scale={track_scale:.2f}"
    )

    return detector, backend_name, detector_mode


def warm_up_detector(detector, input_size, *, skip=False):
    """Run one synthetic frame, then discard its temporal tracking state."""
    width, height = input_size
    if skip:
        warmup_ms = 0.0
        print(
            "Detector warmup skipped; first real detection may take longer.",
            flush=True,
        )
    else:
        print("Detector warmup started...", flush=True)
        warmup_started = time.perf_counter()
        detector.detect(np.zeros((height, width, 3), dtype=np.uint8))
        reset_tracking = getattr(detector, "reset_tracking", None)
        if callable(reset_tracking):
            reset_tracking()
        warmup_ms = (time.perf_counter() - warmup_started) * 1000.0
    return warmup_ms


def load_detector(args: argparse.Namespace, input_size: tuple[int, int], *,
                  calibration_geometry_id: str) -> Any:
    model_backend = str(getattr(args, "inference_backend", "ncnn")).lower()
    model_path, image_size = resolve_model(args, model_backend)
    validate_model_geometry(
        model_path, model_backend, calibration_geometry_id,
        allow_historical=getattr(args, "allow_historical_ncnn_geometry", False),
    )
    detector, backend_name, detector_mode = create_detector(
        args, model_path, image_size, model_backend,
    )
    warmup_ms = warm_up_detector(
        detector, input_size, skip=getattr(args, "skip_detector_warmup", False),
    )
    print(
        f"Detector loaded: model={model_path}; imgsz={image_size}; "
        f"backend={backend_name}; circle={'off' if args.disable_circle_refinement else 'python'}; "
        f"mode={detector_mode}; confidence={args.confidence:.2f}; warmup={warmup_ms:.1f}ms",
        flush=True,
    )
    return detector
