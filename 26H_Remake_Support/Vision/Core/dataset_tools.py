"""Validation and deterministic splitting for steel-ball ROI datasets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import re
from typing import Iterable, Literal

import cv2


IMAGE_SUFFIXES = frozenset((".jpg", ".jpeg", ".png", ".bmp", ".webp"))
SplitMode = Literal["image", "session"]


@dataclass(frozen=True, slots=True)
class RoiDatasetItem:
    session_name: str
    image_path: Path
    label_path: Path
    object_count: int
    width: int
    height: int
    sha256: str
    geometry_id: str | None = None

    @property
    def is_positive(self) -> bool:
        return self.object_count > 0

    @property
    def destination_stem(self) -> str:
        session = re.sub(r"[^A-Za-z0-9_-]+", "_", self.session_name).strip("_")
        if not session:
            session = "session"
        return f"{session}__{self.image_path.stem}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_yolo_label(
    path: str | Path,
    *,
    expected_class_id: int = 0,
    maximum_objects: int = 1,
) -> int:
    """Validate one YOLO label and return its object count."""

    label_path = Path(path)
    try:
        lines = label_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"无法读取标签：{label_path}") from exc

    object_count = 0
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(
                f"{label_path}:{line_number} 必须是 class cx cy w h"
            )
        try:
            class_value = float(fields[0])
            values = [float(value) for value in fields[1:]]
        except ValueError as exc:
            raise ValueError(
                f"{label_path}:{line_number} 包含非数字字段"
            ) from exc
        if not math.isfinite(class_value) or int(class_value) != class_value:
            raise ValueError(
                f"{label_path}:{line_number} 类别编号必须是整数"
            )
        if int(class_value) != expected_class_id:
            raise ValueError(
                f"{label_path}:{line_number} 只允许类别"
                f"{expected_class_id}，实际为{int(class_value)}"
            )
        if not all(math.isfinite(value) for value in values):
            raise ValueError(
                f"{label_path}:{line_number} 坐标必须是有限数值"
            )

        center_x, center_y, width, height = values
        if not 0 <= center_x <= 1 or not 0 <= center_y <= 1:
            raise ValueError(
                f"{label_path}:{line_number} 中心坐标必须在[0,1]内"
            )
        if not 0 < width <= 1 or not 0 < height <= 1:
            raise ValueError(
                f"{label_path}:{line_number} 框宽高必须在(0,1]内"
            )
        tolerance = 1e-6
        if (
            center_x - width * 0.5 < -tolerance
            or center_x + width * 0.5 > 1 + tolerance
            or center_y - height * 0.5 < -tolerance
            or center_y + height * 0.5 > 1 + tolerance
        ):
            raise ValueError(
                f"{label_path}:{line_number} 标注框超出图像边界"
            )
        object_count += 1

    if object_count > maximum_objects:
        raise ValueError(
            f"{label_path} 包含{object_count}个目标；本任务每帧最多"
            f"{maximum_objects}个钢球"
        )
    return object_count


def resolve_session_directories(
    source: str | Path,
) -> tuple[Path, Path, str]:
    """Resolve a capture session root or a direct images directory."""

    path = Path(source).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"采集目录不存在：{path}")
    if (path / "images").is_dir() and (path / "labels").is_dir():
        return path / "images", path / "labels", path.name
    if path.name.lower() == "images" and (path.parent / "labels").is_dir():
        return path, path.parent / "labels", path.parent.name
    raise ValueError(
        f"{path} 必须包含images/和labels/，或直接指向images/目录"
    )


def collect_session_items(
    source: str | Path,
    *,
    expected_size: tuple[int, int] = (640, 128),
) -> list[RoiDatasetItem]:
    """Load all image-label pairs from one capture session."""

    images_dir, labels_dir, session_name = resolve_session_directories(source)
    session_root = images_dir.parent
    session_path = session_root / "session.json"
    if not session_path.is_file():
        # Curated, read-only archives keep the original session record here.
        # A live capture's root session.json always takes precedence.
        session_path = session_root / "source_records" / "capture_session.json"
    geometry_id: str | None = None
    if session_path.is_file():
        try:
            session_payload = json.loads(session_path.read_text(encoding="utf-8"))
            raw_geometry_id = session_payload.get("geometry_id")
            if raw_geometry_id is not None:
                geometry_id = str(raw_geometry_id)
                if len(geometry_id) != 64 or any(
                    character not in "0123456789abcdef"
                    for character in geometry_id.lower()
                ):
                    raise ValueError("geometry_id必须是64位SHA-256")
                geometry_id = geometry_id.lower()
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"采集会话信息无效：{session_path}: {exc}") from exc
    images = sorted(
        path
        for path in images_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not images:
        raise ValueError(f"没有找到训练图片：{images_dir}")

    image_stems = {path.stem for path in images}
    orphan_labels = sorted(
        path
        for path in labels_dir.glob("*.txt")
        if path.stem not in image_stems
    )
    if orphan_labels:
        raise ValueError(f"发现没有对应图片的标签：{orphan_labels[0]}")

    expected_width, expected_height = map(int, expected_size)
    items: list[RoiDatasetItem] = []
    for image_path in images:
        label_path = labels_dir / f"{image_path.stem}.txt"
        if not label_path.is_file():
            raise ValueError(
                f"图片缺少标签：{image_path}；未标注图片不能当作无球负样本"
            )
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise ValueError(f"无法读取图片：{image_path}")
        height, width = image.shape[:2]
        if (width, height) != (expected_width, expected_height):
            raise ValueError(
                f"{image_path} 尺寸为{width}x{height}，要求"
                f"{expected_width}x{expected_height}"
            )
        items.append(
            RoiDatasetItem(
                session_name=session_name,
                image_path=image_path,
                label_path=label_path,
                object_count=validate_yolo_label(label_path),
                width=width,
                height=height,
                sha256=sha256_file(image_path),
                geometry_id=geometry_id,
            )
        )
    return items


def reject_duplicate_images(items: Iterable[RoiDatasetItem]) -> None:
    seen: dict[str, Path] = {}
    for item in items:
        previous = seen.get(item.sha256)
        if previous is not None:
            raise ValueError(
                f"发现完全重复图片：{previous} 和 {item.image_path}"
            )
        seen[item.sha256] = item.image_path


def _validation_count(item_count: int, validation_fraction: float) -> int:
    if item_count < 2:
        return 0
    return min(
        item_count - 1,
        max(1, int(round(item_count * validation_fraction))),
    )


def split_items_by_image(
    items: Iterable[RoiDatasetItem],
    *,
    validation_fraction: float,
    seed: int,
) -> tuple[list[RoiDatasetItem], list[RoiDatasetItem]]:
    """Stratify positive and negative samples with deterministic shuffling."""

    groups = {
        True: [item for item in items if item.is_positive],
        False: [item for item in items if not item.is_positive],
    }
    rng = random.Random(seed)
    train: list[RoiDatasetItem] = []
    validation: list[RoiDatasetItem] = []
    for group in groups.values():
        rng.shuffle(group)
        count = _validation_count(len(group), validation_fraction)
        validation.extend(group[:count])
        train.extend(group[count:])

    if not train or not validation:
        raise ValueError("数据太少，无法同时建立训练集和验证集")
    rng.shuffle(train)
    rng.shuffle(validation)
    return train, validation


def split_items_by_session(
    items: Iterable[RoiDatasetItem],
    *,
    validation_fraction: float,
    seed: int,
) -> tuple[list[RoiDatasetItem], list[RoiDatasetItem]]:
    """Keep every capture session wholly in either train or validation."""

    groups: dict[str, list[RoiDatasetItem]] = {}
    for item in items:
        groups.setdefault(item.session_name, []).append(item)
    if len(groups) < 2:
        raise ValueError("按会话划分至少需要两个不同采集会话")

    rng = random.Random(seed)
    sessions = list(groups)
    rng.shuffle(sessions)
    target = max(1, int(round(sum(map(len, groups.values())) * validation_fraction)))
    validation_sessions: set[str] = set()
    validation_count = 0
    for session in sessions:
        if len(validation_sessions) >= len(sessions) - 1:
            break
        if validation_count < target:
            validation_sessions.add(session)
            validation_count += len(groups[session])

    train = [
        item
        for session, group in groups.items()
        if session not in validation_sessions
        for item in group
    ]
    validation = [
        item
        for session, group in groups.items()
        if session in validation_sessions
        for item in group
    ]
    if not train or not validation:
        raise ValueError("按会话划分后训练集或验证集为空")
    if not any(item.is_positive for item in train):
        raise ValueError("按会话划分后训练集没有有球样本")
    if not any(item.is_positive for item in validation):
        raise ValueError("按会话划分后验证集没有有球样本")
    return train, validation


def split_items(
    items: Iterable[RoiDatasetItem],
    *,
    validation_fraction: float,
    seed: int,
    mode: SplitMode,
) -> tuple[list[RoiDatasetItem], list[RoiDatasetItem]]:
    materialized = list(items)
    if not 0 < validation_fraction < 1:
        raise ValueError("验证集比例必须在(0,1)内")
    if mode == "image":
        return split_items_by_image(
            materialized,
            validation_fraction=validation_fraction,
            seed=seed,
        )
    if mode == "session":
        return split_items_by_session(
            materialized,
            validation_fraction=validation_fraction,
            seed=seed,
        )
    raise ValueError(f"不支持的数据划分方式：{mode}")
