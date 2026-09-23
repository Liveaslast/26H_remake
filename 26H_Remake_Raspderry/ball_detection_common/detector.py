"""Ultralytics YOLO 检测框与局部圆拟合的组合检测器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Callable

import numpy as np

from .circle_refine import CircleRefineConfig, refine_circle
from .models import BallDetection, CircleRefinement, FrameDetection


CircleRefiner = Callable[
    [np.ndarray, tuple[float, float, float, float], CircleRefineConfig],
    CircleRefinement,
]


@dataclass(frozen=True, slots=True)
class BallDetectorConfig:
    """YOLO 推理和圆精修的集中配置。"""

    model_path: str | Path = "models/balls_ncnn_model"
    image_size: int | tuple[int, int] = 512
    confidence: float = 0.35
    iou_threshold: float = 0.70
    class_id: int = 0
    max_detections: int = 300
    circle: CircleRefineConfig = field(default_factory=CircleRefineConfig)

    def __post_init__(self) -> None:
        raw_size = self.image_size
        if isinstance(raw_size, bool):
            raise ValueError("image_size 必须是整数或(高,宽)")
        if isinstance(raw_size, int):
            normalized_size: int | tuple[int, int] = int(raw_size)
            dimensions = (normalized_size,)
        elif isinstance(raw_size, (tuple, list)) and len(raw_size) == 2:
            try:
                normalized_size = (int(raw_size[0]), int(raw_size[1]))
            except (TypeError, ValueError) as exc:
                raise ValueError("image_size 必须是整数或(高,宽)") from exc
            dimensions = normalized_size
        else:
            raise ValueError("image_size 必须是整数或(高,宽)")
        if any(dimension <= 0 for dimension in dimensions):
            raise ValueError("image_size 的每个维度都必须大于0")
        object.__setattr__(self, "image_size", normalized_size)
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence 必须在 [0, 1] 内")
        if not 0 <= self.iou_threshold <= 1:
            raise ValueError("iou_threshold 必须在 [0, 1] 内")
        if self.class_id < 0:
            raise ValueError("class_id 不能小于 0")
        if self.max_detections <= 0:
            raise ValueError("max_detections 必须大于 0")


def _to_numpy(value: Any) -> np.ndarray:
    """兼容 NumPy、CPU tensor 和 GPU tensor。"""

    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


class BallDetector:
    """检测每颗钢珠，并在 YOLO 框内尝试精修圆心和半径。"""

    def __init__(
        self,
        config: BallDetectorConfig | None = None,
        *,
        model: Any | None = None,
        circle_refiner: CircleRefiner = refine_circle,
    ) -> None:
        self.config = config or BallDetectorConfig()
        self._model = model
        self._circle_refiner = circle_refiner

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError(
                    "未安装 ultralytics，请先安装運行環境所需依賴"
                ) from exc
            # NCNN 目录名本身不一定包含任务信息；本工程固定为目标检测模型。
            self._model = YOLO(str(self.config.model_path), task="detect")
        return self._model

    def detect(self, frame: np.ndarray) -> FrameDetection:
        """检测一帧 BGR/灰度原图并返回结构化结果。"""

        if not isinstance(frame, np.ndarray) or frame.size == 0:
            raise ValueError("frame 必须是非空 numpy.ndarray")

        inference_started = time.perf_counter()
        prediction = self._get_model().predict(
            source=frame,
            imgsz=self.config.image_size,
            conf=self.config.confidence,
            iou=self.config.iou_threshold,
            classes=[self.config.class_id],
            max_det=self.config.max_detections,
            verbose=False,
        )[0]
        inference_ms = (time.perf_counter() - inference_started) * 1000.0

        boxes_object = getattr(prediction, "boxes", None)
        if boxes_object is None or len(boxes_object) == 0:
            return FrameDetection((), inference_ms, 0.0)

        boxes = _to_numpy(boxes_object.xyxy).reshape(-1, 4)
        confidences = _to_numpy(boxes_object.conf).reshape(-1)
        class_ids = _to_numpy(boxes_object.cls).reshape(-1)
        count = min(len(boxes), len(confidences), len(class_ids))

        refinement_started = time.perf_counter()
        detections: list[BallDetection] = []
        for index in range(count):
            class_id = int(round(float(class_ids[index])))
            confidence = float(confidences[index])
            if class_id != self.config.class_id or confidence < self.config.confidence:
                continue

            x1, y1, x2, y2 = (float(value) for value in boxes[index])
            if x2 <= x1 or y2 <= y1:
                continue
            box = (x1, y1, x2, y2)
            refinement = self._circle_refiner(frame, box, self.config.circle)
            if refinement.success:
                center = refinement.center_px
                radius = refinement.radius_px
                source = "ransac"
                coverage: float | None = refinement.arc_coverage
                residual = refinement.mean_residual_px
            else:
                center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
                radius = ((x2 - x1) + (y2 - y1)) / 4.0
                source = "yolo_box"
                coverage = None
                residual = None

            detections.append(
                BallDetection(
                    box_xyxy=box,
                    confidence=confidence,
                    class_id=class_id,
                    center_px=center,
                    radius_px=radius,
                    source=source,
                    arc_coverage=coverage,
                    mean_residual_px=residual,
                    inlier_count=refinement.inlier_count,
                )
            )

        refinement_ms = (time.perf_counter() - refinement_started) * 1000.0
        detections.sort(key=lambda item: item.confidence, reverse=True)
        return FrameDetection(tuple(detections), inference_ms, refinement_ms)
