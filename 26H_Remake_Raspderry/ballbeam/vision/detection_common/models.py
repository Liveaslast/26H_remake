"""钢珠检测模块使用的稳定、与推理后端无关的数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Point = tuple[float, float]
Box = tuple[float, float, float, float]
DetectionSource = Literal["ransac", "yolo_box"]


@dataclass(frozen=True, slots=True)
class CircleRefinement:
    """一次局部圆拟合的结果和质量指标。"""

    success: bool
    center_px: Point
    radius_px: float
    arc_coverage: float
    mean_residual_px: float | None
    inlier_count: int
    candidate_count: int
    reason: str


@dataclass(frozen=True, slots=True)
class BallDetection:
    """单颗钢珠的 YOLO 检测框和最终几何结果。"""

    box_xyxy: Box
    confidence: float
    class_id: int
    center_px: Point
    radius_px: float
    source: DetectionSource
    arc_coverage: float | None = None
    mean_residual_px: float | None = None
    inlier_count: int = 0

    @property
    def diameter_px(self) -> float:
        """返回钢珠直径，单位为像素。"""

        return 2.0 * self.radius_px


@dataclass(frozen=True, slots=True)
class FrameDetection:
    """一帧图像的全部钢珠结果和耗时统计。"""

    balls: tuple[BallDetection, ...]
    inference_ms: float
    refinement_ms: float

    @property
    def count(self) -> int:
        """返回当前帧钢珠数量。"""

        return len(self.balls)
