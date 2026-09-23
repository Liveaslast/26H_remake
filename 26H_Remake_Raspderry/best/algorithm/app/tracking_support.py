"""正式跟踪和无M0跟踪共用的模型、检测器与输出工具。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

from ..core.tracker import DynamicTrackingResult
from ..io.runtime import RuntimeIOError
from ..paths import WORKSPACE_ROOT


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


def load_detector(
    args: argparse.Namespace,
    input_size: tuple[int, int],
    *,
    calibration_geometry_id: str,
) -> Any:
    workspace_text = str(WORKSPACE_ROOT)
    if workspace_text not in sys.path:
        sys.path.insert(0, workspace_text)

    inference_backend = str(getattr(args, "inference_backend", "ncnn")).lower()
    if inference_backend in ("hailo", "hailort"):
        if args.hailo_model is None:
            raise RuntimeIOError(
                "Hailo后端需要指定 --hailo-model，例如 "
                "best/algorithm/hailo_model"
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
            raise RuntimeIOError(
                f"模型geometry_id={model_geometry_id[:12]} 与标定"
                f"geometry_id={calibration_geometry_id[:12]} 不一致"
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
    requested_backend = str(args.ncnn_backend).lower()
    speed_mode = str(args.speed_mode).lower()
    detection_interval = int(args.detection_interval)
    refine_interval = int(args.refine_interval)
    track_scale = float(args.track_scale)
    ncnn_threads = int(args.ncnn_threads)
    backend_name = "ultralytics"
    circle_backend = "python"

    try:
        from ball_detection_runtime.detector import (
            AdaptiveBallDetector,
            detector_config_for_mode,
        )
        from ball_detection_runtime.ncnn_backend import (
            native_ncnn_available,
            native_ncnn_import_error,
        )
    except ImportError as adaptive_error:
        if requested_backend == "cpp":
            raise RuntimeIOError(
                "C++ backend package is unavailable. Keep "
                "ball_detection_runtime beside best/."
            ) from adaptive_error
        print(
            "WARNING: adaptive detector is unavailable; falling back to "
            f"Ultralytics every frame: {adaptive_error}",
            file=sys.stderr,
            flush=True,
        )
        try:
            from ball_detection_common import BallDetector, BallDetectorConfig
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
        detector_mode = "ultralytics-every-frame"
    else:
        native_available = native_ncnn_available()
        if inference_backend in ("hailo", "hailort"):
            use_native = False
            backend_name = inference_backend
            circle_backend = "python"
        elif requested_backend == "cpp" and not native_available:
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
            circle_backend = "cpp" if use_native else "python"
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

    width, height = input_size
    if getattr(args, "skip_detector_warmup", False):
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
    print(
        f"Detector loaded: model={model_path}; imgsz={image_size}; "
        f"backend={backend_name}; circle={circle_backend}; "
        f"mode={detector_mode}; confidence={args.confidence:.2f}; "
        f"warmup={warmup_ms:.1f}ms",
        flush=True,
    )
    return detector


def add_detector_performance_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Add native/adaptive detector controls shared by normal and test mode."""

    parser.add_argument(
        "--ncnn-backend",
        choices=("auto", "cpp", "ultralytics"),
        help="auto prefers native C++ and safely falls back to Ultralytics",
    )
    parser.add_argument(
        "--inference-backend",
        choices=("ncnn", "hailo", "hailort"),
        default="hailort",
        help="hailort uses the Hailo AI HAT; ncnn keeps the CPU backend; hailo uses Ultralytics",
    )
    parser.add_argument(
        "--hailo-model",
        type=Path,
        default=WORKSPACE_ROOT / "best" / "algorithm" / "hailo_model",
        help="Ultralytics Hailo export directory containing best.hef",
    )
    parser.add_argument("--ncnn-threads", type=int)
    parser.add_argument(
        "--speed-mode",
        choices=("precision", "balanced", "performance"),
        help="precision is the control-loop default",
    )
    parser.add_argument(
        "--detection-interval",
        type=int,
        help="run NCNN every N frames; checked LK flow fills intermediate frames",
    )
    parser.add_argument(
        "--refine-interval",
        type=int,
        help="0 uses the speed-mode preset; precision preset is 3",
    )
    parser.add_argument(
        "--track-scale",
        type=float,
        help="optical-flow scale in (0,1]; narrow ROI uses 1.0 for accuracy",
    )


def format_result(
    result: DynamicTrackingResult,
    *,
    fps: float | None = None,
) -> str:
    display_position = (
        result.measurement_position_cm
        if result.measurement_valid and result.measurement_position_cm is not None
        else result.position_cm
    )
    x = "none" if display_position is None else f"{display_position:+.3f}"
    vx = (
        "none"
        if result.velocity_cm_s is None
        else f"{result.velocity_cm_s:+.2f}"
    )
    angle = (
        "none"
        if result.actual_angle_deg is None
        else f"{result.actual_angle_deg:+.3f}"
    )
    lost_ms = (
        "none"
        if result.lost_seconds is None
        else f"{result.lost_seconds * 1000.0:.1f}"
    )
    fps_text = "warming" if fps is None else f"{fps:.1f}"
    return (
        f"x={x}cm vx={vx}cm/s angle={angle}deg "
        f"valid={result.tracking_valid} "
        f"measurement={result.measurement_valid} "
        f"source={result.source} confidence={result.confidence:.2f} "
        f"lost={lost_ms}ms processing={result.processing_ms:.2f}ms "
        f"fps={fps_text} reason={result.reason}"
    )
