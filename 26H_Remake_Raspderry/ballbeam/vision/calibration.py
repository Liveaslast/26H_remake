"""随摆杆实际角度变化的透视展开和一维位置标定核心。

固定在车身上的相机观察转动摆杆时，摆杆四角点和球心的像素位置都会
随角度变化。本模块保存多个角度的标定样本，并在运行时插值四角点和
位置映射系数，再重新计算当前帧的透视矩阵。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np


SCHEMA_NAME = "dynamic-rod-calibration/v1"


class DynamicCalibrationError(ValueError):
    """动态标定数据或输入帧无效。"""


@dataclass(frozen=True, slots=True)
class SourceRoi:
    """Fixed source crop inside the full camera frame."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if any(isinstance(value, bool) for value in values):
            raise DynamicCalibrationError("source_roi 必须使用整数像素")
        x, y, width, height = map(int, values)
        if x < 0 or y < 0 or min(width, height) < 2:
            raise DynamicCalibrationError(
                "source_roi 原点不能为负，宽高必须至少为2"
            )
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)

    @property
    def xywh(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    @property
    def bounds_xyxy(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.x + self.width, self.y + self.height

    def validate_inside(self, source_size: tuple[int, int]) -> None:
        source_width, source_height = map(int, source_size)
        x2 = self.x + self.width
        y2 = self.y + self.height
        if x2 > source_width or y2 > source_height:
            raise DynamicCalibrationError(
                f"source_roi={self.xywh} 超出相机帧 "
                f"{source_width}x{source_height}"
            )

    def crop(self, frame: np.ndarray) -> np.ndarray:
        x2 = self.x + self.width
        y2 = self.y + self.height
        return frame[self.y:y2, self.x:x2]

    def to_dict(self) -> dict[str, int]:
        return {
            "x_px": self.x,
            "y_px": self.y,
            "width_px": self.width,
            "height_px": self.height,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceRoi":
        return cls(
            x=int(payload["x_px"]),
            y=int(payload["y_px"]),
            width=int(payload["width_px"]),
            height=int(payload["height_px"]),
        )


def _finite_array(
    value: Any,
    shape: tuple[int, ...],
    name: str,
) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != shape or not np.isfinite(array).all():
        raise DynamicCalibrationError(
            f"{name} 必须是形状为 {shape} 的有限数值数组"
        )
    return array


def order_quad_points(points: Sequence[Sequence[float]]) -> np.ndarray:
    """把四个角点整理为左上、右上、右下、左下。"""

    pts = _finite_array(points, (4, 2), "source_corners_px")
    sums = pts.sum(axis=1)
    differences = np.diff(pts, axis=1).reshape(-1)
    indices = (
        int(np.argmin(sums)),
        int(np.argmin(differences)),
        int(np.argmax(sums)),
        int(np.argmax(differences)),
    )
    if len(set(indices)) != 4:
        raise DynamicCalibrationError("四个角点重复或围成的区域过于退化")

    ordered = pts[list(indices)].astype(np.float64)
    if abs(float(cv2.contourArea(ordered.astype(np.float32)))) < 100.0:
        raise DynamicCalibrationError("四个角点围成的摆杆区域太小")
    return ordered


def destination_corners(size: tuple[int, int]) -> np.ndarray:
    width, height = map(int, size)
    if width < 2 or height < 2:
        raise DynamicCalibrationError("展开尺寸必须至少为 2x2")
    return np.asarray(
        (
            (0.0, 0.0),
            (float(width - 1), 0.0),
            (float(width - 1), float(height - 1)),
            (0.0, float(height - 1)),
        ),
        dtype=np.float32,
    )


def compute_homography(
    source_corners: Sequence[Sequence[float]],
    output_size: tuple[int, int],
) -> np.ndarray:
    source = order_quad_points(source_corners).astype(np.float32)
    matrix = cv2.getPerspectiveTransform(
        source,
        destination_corners(output_size),
    ).astype(np.float64)
    if (
        matrix.shape != (3, 3)
        or not np.isfinite(matrix).all()
        or abs(float(np.linalg.det(matrix))) < 1e-12
    ):
        raise DynamicCalibrationError("无法根据当前四角点计算有效透视矩阵")
    return matrix


def fit_position_polynomial(
    u_pixels: Sequence[float],
    positions_cm: Sequence[float],
    *,
    output_width: int,
) -> np.ndarray:
    """最小二乘拟合 ``x_cm = a*u^2 + b*u + c``。"""

    u = np.asarray(u_pixels, dtype=np.float64)
    x = np.asarray(positions_cm, dtype=np.float64)
    if u.ndim != 1 or x.ndim != 1 or len(u) != len(x) or len(u) < 3:
        raise DynamicCalibrationError("位置标定至少需要三个一一对应的点")
    if not np.isfinite(u).all() or not np.isfinite(x).all():
        raise DynamicCalibrationError("位置标定点必须是有限数值")
    if np.any(np.diff(x) <= 0):
        raise DynamicCalibrationError("物理位置必须从小到大排列且不能重复")

    order = np.argsort(u)
    sorted_u = u[order]
    sorted_x = x[order]
    if np.any(np.diff(sorted_u) < 1.0):
        raise DynamicCalibrationError("相邻刻度点横坐标过近或重复")
    physical_steps = np.diff(sorted_x)
    if not (np.all(physical_steps > 0) or np.all(physical_steps < 0)):
        raise DynamicCalibrationError(
            "展开图中的物理位置必须保持单调，不能来回折返"
        )

    coefficients = np.polyfit(sorted_u, sorted_x, 2)
    if not np.isfinite(coefficients).all():
        raise DynamicCalibrationError("位置二次曲线拟合失败")

    samples = np.linspace(0.0, float(output_width - 1), 256)
    derivative = 2.0 * coefficients[0] * samples + coefficients[1]
    if np.any(np.abs(derivative) <= 1e-9) or (
        np.min(derivative) < 0.0 < np.max(derivative)
    ):
        raise DynamicCalibrationError("位置曲线在有效像素范围内不单调")
    return coefficients.astype(np.float64)


@dataclass(frozen=True, slots=True)
class AngleCalibrationSample:
    """某一个实测摆杆角度的几何标定。"""

    angle_deg: float
    source_corners_px: np.ndarray
    position_coefficients: np.ndarray

    def __post_init__(self) -> None:
        angle = float(self.angle_deg)
        if not math.isfinite(angle):
            raise DynamicCalibrationError("angle_deg 必须是有限数值")
        corners = order_quad_points(self.source_corners_px)
        coefficients = _finite_array(
            self.position_coefficients,
            (3,),
            "position_coefficients",
        )
        object.__setattr__(self, "angle_deg", angle)
        object.__setattr__(self, "source_corners_px", corners)
        object.__setattr__(self, "position_coefficients", coefficients)

    def to_dict(self) -> dict[str, Any]:
        return {
            "angle_deg": self.angle_deg,
            "source_corners_px": self.source_corners_px.tolist(),
            "position_mapping": {
                "model": "quadratic",
                "coefficients": self.position_coefficients.tolist(),
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AngleCalibrationSample":
        try:
            mapping = payload["position_mapping"]
            return cls(
                angle_deg=float(payload["angle_deg"]),
                source_corners_px=np.asarray(
                    payload["source_corners_px"],
                    dtype=np.float64,
                ),
                position_coefficients=np.asarray(
                    mapping["coefficients"],
                    dtype=np.float64,
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DynamicCalibrationError("角度标定样本字段不完整") from exc


@dataclass(frozen=True, slots=True)
class RectificationState:
    """当前角度插值得到的展开参数。"""

    requested_angle_deg: float
    interpolation_angle_deg: float
    lower_angle_deg: float
    upper_angle_deg: float
    interpolation_ratio: float
    source_corners_px: np.ndarray
    position_coefficients: np.ndarray
    homography: np.ndarray
    source_roi: SourceRoi | None = None

    def pixel_to_cm(self, u_pixel: float) -> float:
        return float(np.polyval(self.position_coefficients, float(u_pixel)))

    def cm_to_pixel(
        self,
        position_cm: float,
        valid_u_range: tuple[float, float],
    ) -> float:
        coefficients = self.position_coefficients.copy()
        coefficients[2] -= float(position_cm)
        low, high = sorted(map(float, valid_u_range))
        candidates = [
            float(root.real)
            for root in np.roots(coefficients)
            if abs(float(root.imag)) < 1e-7
            and low - 1e-6 <= float(root.real) <= high + 1e-6
        ]
        if not candidates:
            raise DynamicCalibrationError(
                f"{position_cm:.3f}cm 不在当前像素映射范围内"
            )
        midpoint = (low + high) / 2.0
        return min(candidates, key=lambda value: abs(value - midpoint))

    def rectified_to_source_pixel(
        self,
        point: Sequence[float],
    ) -> tuple[float, float]:
        """Map one rectified point back into the full camera frame."""

        if len(point) != 2:
            raise DynamicCalibrationError("回映射点必须包含u和v")
        vector = np.asarray((float(point[0]), float(point[1]), 1.0))
        source = np.linalg.inv(self.homography) @ vector
        if abs(float(source[2])) <= 1e-12:
            raise DynamicCalibrationError("展开坐标无法回映射到相机帧")
        x = float(source[0] / source[2])
        y = float(source[1] / source[2])
        if self.source_roi is not None:
            x += self.source_roi.x
            y += self.source_roi.y
        return x, y


@dataclass(frozen=True, slots=True)
class DynamicCalibration:
    """多个角度样本组成的动态摆杆标定。"""

    canonical_size: tuple[int, int]
    samples: tuple[AngleCalibrationSample, ...]
    angle_range_override_deg: tuple[float, float] | None = None
    source_size: tuple[int, int] | None = None
    source_roi: SourceRoi | tuple[int, int, int, int] | None = None
    maximum_angle_margin_deg: float = 0.35
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        width, height = map(int, self.canonical_size)
        destination_corners((width, height))

        ordered_samples = tuple(
            sorted(tuple(self.samples), key=lambda sample: sample.angle_deg)
        )
        if len(ordered_samples) < 2:
            raise DynamicCalibrationError("动态标定至少需要两个不同角度样本")
        angles = np.asarray(
            [sample.angle_deg for sample in ordered_samples],
            dtype=np.float64,
        )
        if np.any(np.diff(angles) < 0.05):
            raise DynamicCalibrationError("相邻实测标定角度过近或重复")

        angle_range_override = self.angle_range_override_deg
        if angle_range_override is not None:
            if len(angle_range_override) != 2:
                raise DynamicCalibrationError("angle_range_deg 必须包含两个数值")
            angle_range_override = tuple(map(float, angle_range_override))
            if (
                not math.isfinite(angle_range_override[0])
                or not math.isfinite(angle_range_override[1])
                or angle_range_override[0] > angle_range_override[1]
            ):
                raise DynamicCalibrationError("angle_range_deg 必须是有效升序范围")
            if (
                angle_range_override[0] > ordered_samples[0].angle_deg
                or angle_range_override[1] < ordered_samples[-1].angle_deg
            ):
                raise DynamicCalibrationError(
                    "angle_range_deg 不能窄于已有角度标定样本范围"
                )

        source_size = self.source_size
        if source_size is not None:
            source_size = tuple(map(int, source_size))
            if len(source_size) != 2 or min(source_size) < 2:
                raise DynamicCalibrationError("source_size 必须是有效宽高")

        source_roi = self.source_roi
        if source_roi is not None and not isinstance(source_roi, SourceRoi):
            try:
                source_roi = SourceRoi(*source_roi)
            except (TypeError, ValueError) as exc:
                raise DynamicCalibrationError(
                    "source_roi 必须是(x,y,width,height)"
                ) from exc
        if source_roi is not None:
            if source_size is None:
                raise DynamicCalibrationError(
                    "source_roi 只能和明确的 source_size 一起使用"
                )
            source_roi.validate_inside(source_size)

        margin = float(self.maximum_angle_margin_deg)
        if not math.isfinite(margin) or margin < 0:
            raise DynamicCalibrationError(
                "maximum_angle_margin_deg 不能为负数"
            )

        for sample in ordered_samples:
            compute_homography(sample.source_corners_px, (width, height))
            if source_roi is not None:
                corners = sample.source_corners_px
                if (
                    np.min(corners[:, 0]) < 0.0
                    or np.max(corners[:, 0]) > source_roi.width - 1
                    or np.min(corners[:, 1]) < 0.0
                    or np.max(corners[:, 1]) > source_roi.height - 1
                ):
                    raise DynamicCalibrationError(
                        f"{sample.angle_deg:+.3f}deg 的四角点超出 "
                        f"{source_roi.width}x{source_roi.height} 粗ROI"
                    )
            u = np.linspace(0.0, float(width - 1), 128)
            derivative = (
                2.0 * sample.position_coefficients[0] * u
                + sample.position_coefficients[1]
            )
            if np.any(np.abs(derivative) <= 1e-9) or (
                np.min(derivative) < 0.0 < np.max(derivative)
            ):
                raise DynamicCalibrationError(
                    f"{sample.angle_deg:+.3f}deg 的位置映射不单调"
                )

        object.__setattr__(self, "canonical_size", (width, height))
        object.__setattr__(self, "samples", ordered_samples)
        object.__setattr__(self, "angle_range_override_deg", angle_range_override)
        object.__setattr__(self, "source_size", source_size)
        object.__setattr__(self, "source_roi", source_roi)
        object.__setattr__(self, "maximum_angle_margin_deg", margin)
        object.__setattr__(
            self,
            "metadata",
            dict(self.metadata or {}),
        )

    @property
    def angle_range_deg(self) -> tuple[float, float]:
        if self.angle_range_override_deg is not None:
            return self.angle_range_override_deg
        return self.samples[0].angle_deg, self.samples[-1].angle_deg

    @property
    def geometry_id(self) -> str:
        """Stable identifier shared by calibration, datasets, and models."""

        payload = {
            "source_size": self.source_size,
            "source_roi": (
                None if self.source_roi is None else self.source_roi.xywh
            ),
            "canonical_size": self.canonical_size,
            "angle_samples": [
                {
                    "angle_deg": sample.angle_deg,
                    "source_corners_px": sample.source_corners_px.tolist(),
                }
                for sample in self.samples
            ],
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def crop_source(self, frame: np.ndarray) -> np.ndarray:
        """Validate the full frame and return the configured fixed crop."""

        if not isinstance(frame, np.ndarray) or frame.size == 0:
            raise DynamicCalibrationError("输入相机帧为空")
        if self.source_size is not None:
            actual_size = (int(frame.shape[1]), int(frame.shape[0]))
            if actual_size != self.source_size:
                raise DynamicCalibrationError(
                    f"相机帧尺寸为 {actual_size[0]}x{actual_size[1]}，"
                    f"标定要求 {self.source_size[0]}x{self.source_size[1]}"
                )
        if self.source_roi is None:
            return frame
        cropped = self.source_roi.crop(frame)
        if cropped.shape[:2] != (
            self.source_roi.height,
            self.source_roi.width,
        ):
            raise DynamicCalibrationError("固定粗ROI裁剪结果尺寸异常")
        return cropped

    def state_for_angle(self, angle_deg: float) -> RectificationState:
        requested = float(angle_deg)
        if not math.isfinite(requested):
            raise DynamicCalibrationError("实际摆杆角度必须是有限数值")

        minimum, maximum = self.angle_range_deg
        if requested < minimum - self.maximum_angle_margin_deg:
            raise DynamicCalibrationError(
                f"实际角度 {requested:+.3f}deg 低于标定范围 "
                f"{minimum:+.3f}deg"
            )
        if requested > maximum + self.maximum_angle_margin_deg:
            raise DynamicCalibrationError(
                f"实际角度 {requested:+.3f}deg 高于标定范围 "
                f"{maximum:+.3f}deg"
            )
        interpolation_angle = min(max(requested, minimum), maximum)

        angles = np.asarray(
            [sample.angle_deg for sample in self.samples],
            dtype=np.float64,
        )
        upper_index = int(np.searchsorted(angles, interpolation_angle))
        if upper_index == 0:
            lower_index = upper_index = 0
        elif upper_index >= len(self.samples):
            lower_index = upper_index = len(self.samples) - 1
        elif abs(interpolation_angle - angles[upper_index]) < 1e-9:
            lower_index = upper_index
        else:
            lower_index = upper_index - 1

        lower = self.samples[lower_index]
        upper = self.samples[upper_index]
        if lower_index == upper_index:
            ratio = 0.0
        else:
            ratio = (
                (interpolation_angle - lower.angle_deg)
                / (upper.angle_deg - lower.angle_deg)
            )

        corners = (
            (1.0 - ratio) * lower.source_corners_px
            + ratio * upper.source_corners_px
        )
        coefficients = (
            (1.0 - ratio) * lower.position_coefficients
            + ratio * upper.position_coefficients
        )
        homography = compute_homography(corners, self.canonical_size)
        return RectificationState(
            requested_angle_deg=requested,
            interpolation_angle_deg=interpolation_angle,
            lower_angle_deg=lower.angle_deg,
            upper_angle_deg=upper.angle_deg,
            interpolation_ratio=float(ratio),
            source_corners_px=corners,
            position_coefficients=coefficients,
            homography=homography,
            source_roi=self.source_roi,
        )

    def rectify(
        self,
        frame: np.ndarray,
        angle_deg: float,
    ) -> tuple[np.ndarray, RectificationState]:
        source = self.crop_source(frame)
        state = self.state_for_angle(angle_deg)
        rectified = cv2.warpPerspective(
            source,
            state.homography,
            self.canonical_size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        return rectified, state

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_NAME,
            "source": (
                None
                if self.source_size is None
                else {
                    "width_px": self.source_size[0],
                    "height_px": self.source_size[1],
                    "roi": (
                        None
                        if self.source_roi is None
                        else self.source_roi.to_dict()
                    ),
                }
            ),
            "rectification": {
                "width_px": self.canonical_size[0],
                "height_px": self.canonical_size[1],
            },
            "maximum_angle_margin_deg": self.maximum_angle_margin_deg,
            "angle_range_deg": self.angle_range_override_deg,
            "geometry_id": self.geometry_id,
            "samples": [sample.to_dict() for sample in self.samples],
            "metadata": dict(self.metadata or {}),
        }

    def save(self, path: str | Path) -> None:
        output = Path(path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DynamicCalibration":
        if payload.get("schema") != SCHEMA_NAME:
            raise DynamicCalibrationError(
                f"不支持的标定格式：{payload.get('schema')!r}"
            )
        try:
            rectification = payload["rectification"]
            canonical_size = (
                int(rectification["width_px"]),
                int(rectification["height_px"]),
            )
            source_payload = payload.get("source")
            source_size = (
                None
                if source_payload is None
                else (
                    int(source_payload["width_px"]),
                    int(source_payload["height_px"]),
                )
            )
            roi_payload = (
                None
                if source_payload is None
                else source_payload.get("roi")
            )
            source_roi = (
                None
                if roi_payload is None
                else SourceRoi.from_dict(roi_payload)
            )
            samples = tuple(
                AngleCalibrationSample.from_dict(sample)
                for sample in payload["samples"]
            )
            calibration = cls(
                canonical_size=canonical_size,
                source_size=source_size,
                source_roi=source_roi,
                samples=samples,
                angle_range_override_deg=(
                    None
                    if payload.get("angle_range_deg") is None
                    else tuple(float(value) for value in payload["angle_range_deg"])
                ),
                maximum_angle_margin_deg=float(
                    payload.get("maximum_angle_margin_deg", 0.35)
                ),
                metadata=dict(payload.get("metadata") or {}),
            )
            stored_geometry_id = payload.get("geometry_id")
            if (
                stored_geometry_id is not None
                and str(stored_geometry_id) != calibration.geometry_id
            ):
                raise DynamicCalibrationError(
                    "标定文件geometry_id校验失败，文件可能被手工改动或损坏"
                )
            return calibration
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, DynamicCalibrationError):
                raise
            raise DynamicCalibrationError("动态标定文件字段不完整") from exc

    @classmethod
    def load(cls, path: str | Path) -> "DynamicCalibration":
        input_path = Path(path).expanduser()
        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise DynamicCalibrationError(
                f"无法读取标定文件：{input_path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise DynamicCalibrationError(
                f"标定文件不是有效 JSON：{input_path}"
            ) from exc
        if not isinstance(payload, dict):
            raise DynamicCalibrationError("标定文件根节点必须是 JSON 对象")
        return cls.from_dict(payload)
