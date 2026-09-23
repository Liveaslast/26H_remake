"""在 YOLO 检测框附近使用边缘和 RANSAC 精修钢珠圆心。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Sequence

import cv2
import numpy as np

from .models import CircleRefinement


_RANSAC_MAX_BATCH_SIZE = 75
_RANSAC_WORKING_BYTES_LIMIT = 8 * 1024 * 1024
_RANSAC_ESTIMATED_BYTES_PER_DISTANCE = 32


@dataclass(frozen=True, slots=True)
class CircleRefineConfig:
    """局部边缘筛选、RANSAC 和质量检查参数。"""

    roi_expand_ratio: float = 0.20
    blur_kernel_size: int = 5
    canny_low: int = 50
    canny_high: int = 150
    annulus_inner_ratio: float = 0.58
    annulus_outer_ratio: float = 1.45
    min_gradient_alignment: float = 0.25
    ransac_iterations: int = 500
    inlier_threshold_px: float = 2.0
    min_radius_ratio: float = 0.65
    max_radius_ratio: float = 1.25
    max_center_offset_ratio: float = 0.25
    angle_bins: int = 36
    min_arc_coverage: float = 0.32
    max_mean_residual_px: float = 2.0
    min_candidate_points: int = 20
    min_inliers: int = 12
    random_seed: int = 0

    def __post_init__(self) -> None:
        if self.roi_expand_ratio < 0:
            raise ValueError("roi_expand_ratio 不能小于 0")
        if self.blur_kernel_size < 1 or self.blur_kernel_size % 2 == 0:
            raise ValueError("blur_kernel_size 必须是正奇数")
        if not 0 <= self.canny_low < self.canny_high:
            raise ValueError("Canny 阈值必须满足 0 <= low < high")
        if not 0 < self.annulus_inner_ratio < self.annulus_outer_ratio:
            raise ValueError("候选环带比例设置无效")
        if not 0 <= self.min_gradient_alignment <= 1:
            raise ValueError("min_gradient_alignment 必须在 [0, 1] 内")
        if self.ransac_iterations <= 0:
            raise ValueError("ransac_iterations 必须大于 0")
        if self.inlier_threshold_px <= 0:
            raise ValueError("inlier_threshold_px 必须大于 0")
        if not 0 < self.min_radius_ratio <= self.max_radius_ratio:
            raise ValueError("半径比例设置无效")
        if self.max_center_offset_ratio < 0:
            raise ValueError("max_center_offset_ratio 不能小于 0")
        if self.angle_bins < 4:
            raise ValueError("angle_bins 不能小于 4")
        if not 0 <= self.min_arc_coverage <= 1:
            raise ValueError("min_arc_coverage 必须在 [0, 1] 内")
        if self.max_mean_residual_px <= 0:
            raise ValueError("max_mean_residual_px 必须大于 0")
        if self.min_candidate_points < 3 or self.min_inliers < 3:
            raise ValueError("候选点数和内点数都不能小于 3")


@dataclass(frozen=True, slots=True)
class _Circle:
    center_x: float
    center_y: float
    radius: float


def _fallback_result(
    center: tuple[float, float],
    radius: float,
    candidate_count: int,
    reason: str,
    *,
    arc_coverage: float = 0.0,
    mean_residual_px: float | None = None,
    inlier_count: int = 0,
) -> CircleRefinement:
    return CircleRefinement(
        success=False,
        center_px=center,
        radius_px=radius,
        arc_coverage=arc_coverage,
        mean_residual_px=mean_residual_px,
        inlier_count=inlier_count,
        candidate_count=candidate_count,
        reason=reason,
    )


def _circle_from_three(points: np.ndarray) -> _Circle | None:
    """计算三个非共线点的外接圆。"""

    (x1, y1), (x2, y2), (x3, y3) = points
    denominator = 2.0 * (
        x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)
    )
    if abs(denominator) < 1e-8:
        return None

    norm1 = x1 * x1 + y1 * y1
    norm2 = x2 * x2 + y2 * y2
    norm3 = x3 * x3 + y3 * y3
    center_x = (
        norm1 * (y2 - y3)
        + norm2 * (y3 - y1)
        + norm3 * (y1 - y2)
    ) / denominator
    center_y = (
        norm1 * (x3 - x2)
        + norm2 * (x1 - x3)
        + norm3 * (x2 - x1)
    ) / denominator
    radius = math.hypot(x1 - center_x, y1 - center_y)
    if not all(math.isfinite(value) for value in (center_x, center_y, radius)):
        return None
    return _Circle(center_x, center_y, radius)


def _least_squares_circle(points: np.ndarray) -> _Circle | None:
    """使用所有 RANSAC 内点对圆参数做线性最小二乘精修。"""

    matrix = np.column_stack(
        (2.0 * points[:, 0], 2.0 * points[:, 1], np.ones(len(points)))
    )
    target = points[:, 0] ** 2 + points[:, 1] ** 2
    try:
        solution, _, rank, _ = np.linalg.lstsq(matrix, target, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if rank < 3:
        return None
    center_x, center_y, constant = solution
    radius_squared = constant + center_x**2 + center_y**2
    if radius_squared <= 0:
        return None
    radius = math.sqrt(float(radius_squared))
    if not all(math.isfinite(float(value)) for value in (center_x, center_y, radius)):
        return None
    return _Circle(float(center_x), float(center_y), radius)


def _residuals(points: np.ndarray, circle: _Circle) -> np.ndarray:
    distances = np.hypot(
        points[:, 0] - circle.center_x,
        points[:, 1] - circle.center_y,
    )
    return np.abs(distances - circle.radius)


def _within_geometry_limits(
    circle: _Circle,
    box_center: tuple[float, float],
    expected_radius: float,
    max_box_side: float,
    config: CircleRefineConfig,
) -> bool:
    if not (
        config.min_radius_ratio * expected_radius
        <= circle.radius
        <= config.max_radius_ratio * expected_radius
    ):
        return False
    center_offset = math.hypot(
        circle.center_x - box_center[0],
        circle.center_y - box_center[1],
    )
    return center_offset <= config.max_center_offset_ratio * max_box_side


def _sample_ransac_triplets(
    rng: np.random.Generator,
    candidate_count: int,
    iterations: int,
) -> np.ndarray:
    """Draw every triplet up front while preserving the legacy RNG sequence."""

    samples = np.empty((iterations, 3), dtype=np.intp)
    for index in range(iterations):
        samples[index] = rng.choice(candidate_count, size=3, replace=False)
    return samples


@lru_cache(maxsize=128)
def _cached_ransac_triplets(
    candidate_count: int,
    iterations: int,
    random_seed: int,
) -> np.ndarray:
    """Cache the exact legacy sample sequence for deterministic runs."""

    samples = _sample_ransac_triplets(
        np.random.default_rng(random_seed),
        candidate_count,
        iterations,
    )
    samples.flags.writeable = False
    return samples


def _ransac_batch_size(candidate_count: int, iterations: int) -> int:
    """Use one full batch normally, with a bound on temporary array memory."""

    bytes_per_hypothesis = max(
        1,
        candidate_count * _RANSAC_ESTIMATED_BYTES_PER_DISTANCE,
    )
    memory_limited_size = max(
        1,
        _RANSAC_WORKING_BYTES_LIMIT // bytes_per_hypothesis,
    )
    return min(iterations, _RANSAC_MAX_BATCH_SIZE, memory_limited_size)


def _circles_from_triplets(sampled_points: np.ndarray) -> tuple[np.ndarray, ...]:
    """Calculate a batch of three-point circle hypotheses."""

    x1, y1 = sampled_points[:, 0, 0], sampled_points[:, 0, 1]
    x2, y2 = sampled_points[:, 1, 0], sampled_points[:, 1, 1]
    x3, y3 = sampled_points[:, 2, 0], sampled_points[:, 2, 1]
    denominator = 2.0 * (
        x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)
    )
    valid = np.abs(denominator) >= 1e-8

    center_x = np.full(len(sampled_points), np.nan, dtype=np.float64)
    center_y = np.full(len(sampled_points), np.nan, dtype=np.float64)
    radius = np.full(len(sampled_points), np.nan, dtype=np.float64)
    if np.any(valid):
        norm1 = x1 * x1 + y1 * y1
        norm2 = x2 * x2 + y2 * y2
        norm3 = x3 * x3 + y3 * y3
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            center_x[valid] = (
                norm1[valid] * (y2[valid] - y3[valid])
                + norm2[valid] * (y3[valid] - y1[valid])
                + norm3[valid] * (y1[valid] - y2[valid])
            ) / denominator[valid]
            center_y[valid] = (
                norm1[valid] * (x3[valid] - x2[valid])
                + norm2[valid] * (x1[valid] - x3[valid])
                + norm3[valid] * (x2[valid] - x1[valid])
            ) / denominator[valid]
            radius[valid] = np.hypot(
                x1[valid] - center_x[valid],
                y1[valid] - center_y[valid],
            )

    valid &= np.isfinite(center_x) & np.isfinite(center_y) & np.isfinite(radius)
    return center_x, center_y, radius, valid


def _run_ransac(
    points: np.ndarray,
    box_center: tuple[float, float],
    expected_radius: float,
    max_box_side: float,
    config: CircleRefineConfig,
    rng: np.random.Generator | None,
) -> tuple[_Circle | None, np.ndarray | None]:
    """Select the best circle using batched hypotheses and exact final scoring."""

    candidate_count = len(points)
    if rng is None:
        sample_indices = _cached_ransac_triplets(
            candidate_count,
            config.ransac_iterations,
            config.random_seed,
        )
    else:
        sample_indices = _sample_ransac_triplets(
            rng,
            candidate_count,
            config.ransac_iterations,
        )
    best_circle: _Circle | None = None
    best_inlier_mask: np.ndarray | None = None
    best_score = (-1, -math.inf)
    threshold = config.inlier_threshold_px

    batch_size = _ransac_batch_size(candidate_count, config.ransac_iterations)
    for start in range(0, config.ransac_iterations, batch_size):
        stop = min(start + batch_size, config.ransac_iterations)
        center_x, center_y, radius, valid = _circles_from_triplets(
            points[sample_indices[start:stop]]
        )

        circles: list[_Circle | None] = [None] * (stop - start)
        geometry_rows: list[int] = []
        for row in np.flatnonzero(valid):
            candidate = _Circle(
                float(center_x[row]),
                float(center_y[row]),
                float(radius[row]),
            )
            if _within_geometry_limits(
                candidate,
                box_center,
                expected_radius,
                max_box_side,
                config,
            ):
                circles[row] = candidate
                geometry_rows.append(int(row))
        if not geometry_rows:
            continue

        rows = np.asarray(geometry_rows, dtype=np.intp)
        batch_center_x = center_x[rows]
        batch_center_y = center_y[rows]
        batch_radius = radius[rows]
        delta_x = points[None, :, 0] - batch_center_x[:, None]
        delta_y = points[None, :, 1] - batch_center_y[:, None]
        distance_squared = delta_x * delta_x + delta_y * delta_y

        lower = np.maximum(0.0, batch_radius - threshold)
        upper = batch_radius + threshold
        # Round the squared bounds outwards.  The mask is only a cheap
        # prefilter and must not discard a hypothesis accepted by the exact
        # residual calculation below.
        lower_squared = np.nextafter(lower * lower, -np.inf)[:, None]
        upper_squared = np.nextafter(upper * upper, np.inf)[:, None]
        approximate_masks = (
            (distance_squared >= lower_squared)
            & (distance_squared <= upper_squared)
        )
        approximate_counts = np.count_nonzero(approximate_masks, axis=1)

        for batch_row, row in enumerate(geometry_rows):
            if approximate_counts[batch_row] < max(
                config.min_inliers,
                best_score[0],
            ):
                continue
            candidate = circles[row]
            assert candidate is not None
            residual = _residuals(points, candidate)
            inlier_mask = residual <= threshold
            inlier_count = int(np.count_nonzero(inlier_mask))
            if inlier_count < config.min_inliers or inlier_count < best_score[0]:
                continue
            mean_inlier_residual = float(np.mean(residual[inlier_mask]))
            score = (inlier_count, -mean_inlier_residual)
            if score > best_score:
                best_score = score
                best_circle = candidate
                best_inlier_mask = inlier_mask

    return best_circle, best_inlier_mask


def refine_circle(
    frame: np.ndarray,
    box_xyxy: Sequence[float],
    config: CircleRefineConfig | None = None,
    *,
    rng: np.random.Generator | None = None,
) -> CircleRefinement:
    """在原图的检测框附近拟合圆，不通过质量检查时返回框几何。"""

    config = config or CircleRefineConfig()
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise ValueError("frame 必须是非空 numpy.ndarray")
    if frame.ndim not in (2, 3):
        raise ValueError("frame 必须是灰度图或彩色图")
    if len(box_xyxy) != 4:
        raise ValueError("box_xyxy 必须包含四个坐标")

    x1, y1, x2, y2 = (float(value) for value in box_xyxy)
    if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
        raise ValueError("检测框坐标必须是有限数")
    width = x2 - x1
    height = y2 - y1
    if width <= 0 or height <= 0:
        raise ValueError("检测框宽度和高度必须大于 0")

    box_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    expected_radius = (width + height) / 4.0
    max_box_side = max(width, height)

    padding_x = width * config.roi_expand_ratio
    padding_y = height * config.roi_expand_ratio
    frame_height, frame_width = frame.shape[:2]
    left = max(0, int(math.floor(x1 - padding_x)))
    top = max(0, int(math.floor(y1 - padding_y)))
    right = min(frame_width, int(math.ceil(x2 + padding_x)) + 1)
    bottom = min(frame_height, int(math.ceil(y2 + padding_y)) + 1)
    if left >= right or top >= bottom:
        return _fallback_result(box_center, expected_radius, 0, "ROI 不在图像范围内")

    roi = frame[top:bottom, left:right]
    if roi.ndim == 3:
        if roi.shape[2] == 4:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGRA2GRAY)
        elif roi.shape[2] == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            raise ValueError("彩色 frame 必须有 3 或 4 个通道")
    else:
        gray = roi
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    blurred = cv2.GaussianBlur(
        gray,
        (config.blur_kernel_size, config.blur_kernel_size),
        0,
    )
    edges = cv2.Canny(blurred, config.canny_low, config.canny_high)
    gradient_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)

    local_y, local_x = np.nonzero(edges)
    if local_x.size == 0:
        return _fallback_result(box_center, expected_radius, 0, "ROI 中没有边缘")
    global_x = local_x.astype(np.float64) + left
    global_y = local_y.astype(np.float64) + top
    radial_x = global_x - box_center[0]
    radial_y = global_y - box_center[1]
    radial_distance = np.hypot(radial_x, radial_y)

    sampled_gradient_x = gradient_x[local_y, local_x].astype(np.float64)
    sampled_gradient_y = gradient_y[local_y, local_x].astype(np.float64)
    gradient_norm = np.hypot(sampled_gradient_x, sampled_gradient_y)
    denominator = gradient_norm * np.maximum(radial_distance, 1e-8)
    alignment = np.zeros_like(denominator)
    valid_denominator = denominator > 1e-8
    alignment[valid_denominator] = np.abs(
        sampled_gradient_x[valid_denominator] * radial_x[valid_denominator]
        + sampled_gradient_y[valid_denominator] * radial_y[valid_denominator]
    ) / denominator[valid_denominator]

    candidate_mask = (
        (radial_distance >= config.annulus_inner_ratio * expected_radius)
        & (radial_distance <= config.annulus_outer_ratio * expected_radius)
        & (alignment >= config.min_gradient_alignment)
    )
    points = np.column_stack((global_x[candidate_mask], global_y[candidate_mask]))
    candidate_count = len(points)
    if candidate_count < config.min_candidate_points:
        return _fallback_result(
            box_center,
            expected_radius,
            candidate_count,
            "有效候选边缘点不足",
        )

    best_circle, best_inlier_mask = _run_ransac(
        points,
        box_center,
        expected_radius,
        max_box_side,
        config,
        rng,
    )

    if best_circle is None or best_inlier_mask is None:
        return _fallback_result(
            box_center,
            expected_radius,
            candidate_count,
            "RANSAC 未找到满足几何约束的圆",
        )

    refined = _least_squares_circle(points[best_inlier_mask])
    if refined is None:
        return _fallback_result(
            box_center,
            expected_radius,
            candidate_count,
            "最小二乘精修失败",
            inlier_count=int(np.count_nonzero(best_inlier_mask)),
        )
    if not _within_geometry_limits(
        refined,
        box_center,
        expected_radius,
        max_box_side,
        config,
    ):
        return _fallback_result(
            box_center,
            expected_radius,
            candidate_count,
            "精修圆超出半径或圆心约束",
        )

    final_residuals = _residuals(points, refined)
    final_inlier_mask = final_residuals <= config.inlier_threshold_px
    final_points = points[final_inlier_mask]
    inlier_count = len(final_points)
    if inlier_count < config.min_inliers:
        return _fallback_result(
            box_center,
            expected_radius,
            candidate_count,
            "精修后的内点不足",
            inlier_count=inlier_count,
        )

    mean_residual = float(np.mean(final_residuals[final_inlier_mask]))
    angles = np.mod(
        np.arctan2(
            final_points[:, 1] - refined.center_y,
            final_points[:, 0] - refined.center_x,
        ),
        2.0 * math.pi,
    )
    bins = np.floor(angles / (2.0 * math.pi) * config.angle_bins).astype(int)
    bins = np.clip(bins, 0, config.angle_bins - 1)
    arc_coverage = len(np.unique(bins)) / config.angle_bins

    if arc_coverage < config.min_arc_coverage:
        return _fallback_result(
            box_center,
            expected_radius,
            candidate_count,
            "圆弧覆盖率不足",
            arc_coverage=arc_coverage,
            mean_residual_px=mean_residual,
            inlier_count=inlier_count,
        )
    if mean_residual > config.max_mean_residual_px:
        return _fallback_result(
            box_center,
            expected_radius,
            candidate_count,
            "平均圆周残差过大",
            arc_coverage=arc_coverage,
            mean_residual_px=mean_residual,
            inlier_count=inlier_count,
        )

    return CircleRefinement(
        success=True,
        center_px=(refined.center_x, refined.center_y),
        radius_px=refined.radius,
        arc_coverage=arc_coverage,
        mean_residual_px=mean_residual,
        inlier_count=inlier_count,
        candidate_count=candidate_count,
        reason="圆拟合质量检查通过",
    )
