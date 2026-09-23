"""ROI dataset preparation and atomic sample storage helpers.

The detector input is produced with aspect-ratio-preserving resize plus padding.
This keeps a circular steel ball circular instead of stretching the very wide
rectified groove ROI to fill a rectangular network input.
"""

from __future__ import annotations

from collections import Counter
import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np


LabelState = Literal["positive", "negative", "unlabeled"]


@dataclass(frozen=True, slots=True)
class LetterboxInfo:
    """Geometry used to place a source ROI in a fixed detector input."""

    source_width: int
    source_height: int
    output_width: int
    output_height: int
    resized_width: int
    resized_height: int
    pad_left: int
    pad_top: int
    pad_right: int
    pad_bottom: int
    scale_x: float
    scale_y: float

    @property
    def content_bounds_xyxy(self) -> tuple[int, int, int, int]:
        return (
            self.pad_left,
            self.pad_top,
            self.pad_left + self.resized_width,
            self.pad_top + self.resized_height,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["content_bounds_xyxy"] = list(self.content_bounds_xyxy)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LetterboxInfo":
        """Restore persisted resize geometry, ignoring derived fields."""

        return cls(
            source_width=int(payload["source_width"]),
            source_height=int(payload["source_height"]),
            output_width=int(payload["output_width"]),
            output_height=int(payload["output_height"]),
            resized_width=int(payload["resized_width"]),
            resized_height=int(payload["resized_height"]),
            pad_left=int(payload["pad_left"]),
            pad_top=int(payload["pad_top"]),
            pad_right=int(payload["pad_right"]),
            pad_bottom=int(payload["pad_bottom"]),
            scale_x=float(payload["scale_x"]),
            scale_y=float(payload["scale_y"]),
        )


def letterbox_roi(
    image: np.ndarray,
    output_size: tuple[int, int],
    *,
    padding_value: int = 114,
) -> tuple[np.ndarray, LetterboxInfo]:
    """Resize ``image`` isotropically and center-pad it to ``(width, height)``."""

    if not isinstance(image, np.ndarray) or image.size == 0:
        raise ValueError("ROI图像不能为空")
    if image.ndim not in (2, 3):
        raise ValueError("ROI图像必须是灰度图或彩色图")

    source_height, source_width = image.shape[:2]
    output_width, output_height = map(int, output_size)
    if min(source_width, source_height, output_width, output_height) < 2:
        raise ValueError("ROI和模型输入尺寸必须至少为2x2")
    if not 0 <= padding_value <= 255:
        raise ValueError("填充值必须在[0,255]内")

    scale = min(
        output_width / source_width,
        output_height / source_height,
    )
    resized_width = min(
        output_width,
        max(1, int(round(source_width * scale))),
    )
    resized_height = min(
        output_height,
        max(1, int(round(source_height * scale))),
    )
    interpolation = (
        cv2.INTER_AREA
        if scale < 1.0
        else cv2.INTER_LINEAR
    )
    resized = cv2.resize(
        image,
        (resized_width, resized_height),
        interpolation=interpolation,
    )

    pad_left = (output_width - resized_width) // 2
    pad_right = output_width - resized_width - pad_left
    pad_top = (output_height - resized_height) // 2
    pad_bottom = output_height - resized_height - pad_top
    if image.ndim == 2:
        canvas = np.full(
            (output_height, output_width),
            padding_value,
            dtype=image.dtype,
        )
    else:
        canvas = np.full(
            (output_height, output_width, image.shape[2]),
            padding_value,
            dtype=image.dtype,
        )
    canvas[
        pad_top : pad_top + resized_height,
        pad_left : pad_left + resized_width,
    ] = resized

    info = LetterboxInfo(
        source_width=source_width,
        source_height=source_height,
        output_width=output_width,
        output_height=output_height,
        resized_width=resized_width,
        resized_height=resized_height,
        pad_left=pad_left,
        pad_top=pad_top,
        pad_right=pad_right,
        pad_bottom=pad_bottom,
        scale_x=resized_width / source_width,
        scale_y=resized_height / source_height,
    )
    return canvas, info


def yolo_box_from_xywh(
    box_xywh: tuple[float, float, float, float],
    image_size: tuple[int, int],
    *,
    minimum_size_px: float = 2.0,
) -> tuple[float, float, float, float]:
    """Clamp a pixel box and return normalized YOLO ``cx cy w h``."""

    image_width, image_height = map(float, image_size)
    if image_width < 2 or image_height < 2:
        raise ValueError("标注图像尺寸无效")
    x, y, width, height = map(float, box_xywh)
    x1 = min(image_width, max(0.0, x))
    y1 = min(image_height, max(0.0, y))
    x2 = min(image_width, max(0.0, x + width))
    y2 = min(image_height, max(0.0, y + height))
    clipped_width = x2 - x1
    clipped_height = y2 - y1
    if clipped_width < minimum_size_px or clipped_height < minimum_size_px:
        raise ValueError("钢球框太小或没有有效面积")

    return (
        ((x1 + x2) * 0.5) / image_width,
        ((y1 + y2) * 0.5) / image_height,
        clipped_width / image_width,
        clipped_height / image_height,
    )


@dataclass(frozen=True, slots=True)
class SavedSample:
    sample_id: str
    label_state: LabelState
    record: dict[str, Any]


class RoiDatasetWriter:
    """Store synchronized source, rectified and training-input images."""

    def __init__(
        self,
        session_dir: str | Path,
        *,
        prefix: str = "roi",
        save_source: bool = True,
        source_jpeg_quality: int = 95,
        png_compression: int = 3,
        append_existing: bool = False,
    ) -> None:
        self.session_dir = Path(session_dir).expanduser().resolve()
        if (
            self.session_dir.exists()
            and any(self.session_dir.iterdir())
            and not append_existing
        ):
            raise FileExistsError(
                f"采集会话目录已经存在且非空，拒绝覆盖：{self.session_dir}"
            )
        if not prefix or not prefix.replace("_", "").isalnum():
            raise ValueError("样本前缀只能包含字母、数字和下划线")
        if not 1 <= source_jpeg_quality <= 100:
            raise ValueError("原图JPEG质量必须在[1,100]内")
        if not 0 <= png_compression <= 9:
            raise ValueError("PNG压缩级别必须在[0,9]内")

        self.prefix = prefix
        self.save_source = bool(save_source)
        self.source_jpeg_quality = int(source_jpeg_quality)
        self.png_compression = int(png_compression)
        self._next_index = 1
        self._records: list[dict[str, Any]] = []

        self.session_dir.mkdir(parents=True, exist_ok=True)
        for directory in (
            "images",
            "labels",
            "unlabeled",
            "rectified",
            "source",
            "source_roi",
        ):
            (self.session_dir / directory).mkdir(exist_ok=True)

        if append_existing:
            self._load_existing_records()

    @property
    def metadata_path(self) -> Path:
        return self.session_dir / "metadata.jsonl"

    @property
    def sample_count(self) -> int:
        return len(self._records)

    @property
    def counts(self) -> dict[str, int]:
        values = Counter(record["label_state"] for record in self._records)
        return {
            "positive": values["positive"],
            "negative": values["negative"],
            "unlabeled": values["unlabeled"],
            "total": len(self._records),
        }

    @property
    def unlabeled_samples(self) -> tuple[SavedSample, ...]:
        """Return stable snapshots of samples waiting for annotation."""

        return tuple(
            SavedSample(
                sample_id=str(record["sample_id"]),
                label_state="unlabeled",
                record=copy.deepcopy(record),
            )
            for record in self._records
            if record["label_state"] == "unlabeled"
        )

    def write_session(self, payload: dict[str, Any]) -> Path:
        output = self.session_dir / "session.json"
        if output.exists():
            return output
        document = {
            "schema": "steel-ball-roi-capture-session/v1",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        output.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return output

    def _load_existing_records(self) -> None:
        if not self.metadata_path.exists():
            return

        records: list[dict[str, Any]] = []
        with self.metadata_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"metadata.jsonl第{line_number}行不是有效JSON"
                    ) from exc
                if not isinstance(record, dict):
                    raise ValueError(
                        f"metadata.jsonl第{line_number}行不是样本记录"
                    )
                sample_id = str(record.get("sample_id", ""))
                if not sample_id.startswith(f"{self.prefix}_"):
                    continue
                records.append(record)

        self._records = records
        if records:
            self._next_index = max(int(record["index"]) for record in records) + 1

    def save_sample(
        self,
        *,
        source_frame: np.ndarray,
        rectified_roi: np.ndarray,
        model_input: np.ndarray,
        source_roi_frame: np.ndarray | None = None,
        captured_monotonic: float,
        angle_deg: float,
        label_state: LabelState,
        letterbox_info: LetterboxInfo,
        yolo_box: tuple[float, float, float, float] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> SavedSample:
        if label_state not in ("positive", "negative", "unlabeled"):
            raise ValueError(f"不支持的标签状态：{label_state}")
        if label_state == "positive" and yolo_box is None:
            raise ValueError("有球样本必须提供YOLO钢球框")
        if label_state != "positive" and yolo_box is not None:
            raise ValueError("只有有球样本可以提供YOLO钢球框")
        for name, image in (
            ("source_frame", source_frame),
            ("rectified_roi", rectified_roi),
            ("model_input", model_input),
        ):
            if not isinstance(image, np.ndarray) or image.size == 0:
                raise ValueError(f"{name}不能为空")
        if source_roi_frame is not None and (
            not isinstance(source_roi_frame, np.ndarray)
            or source_roi_frame.size == 0
        ):
            raise ValueError("source_roi_frame不能为空")

        index = self._next_index
        sample_id = f"{self.prefix}_{index:06d}"
        image_directory = (
            "unlabeled" if label_state == "unlabeled" else "images"
        )
        relative_paths: dict[str, str | None] = {
            "model_input": f"{image_directory}/{sample_id}.png",
            "rectified": f"rectified/{sample_id}.png",
            "source": (
                f"source/{sample_id}.jpg"
                if self.save_source
                else None
            ),
            "source_roi": (
                f"source_roi/{sample_id}.png"
                if self.save_source and source_roi_frame is not None
                else None
            ),
            "label": (
                None
                if label_state == "unlabeled"
                else f"labels/{sample_id}.txt"
            ),
        }
        created_paths: list[Path] = []

        try:
            model_path = self.session_dir / relative_paths["model_input"]
            self._write_image(
                model_path,
                model_input,
                [cv2.IMWRITE_PNG_COMPRESSION, self.png_compression],
            )
            created_paths.append(model_path)

            rectified_path = self.session_dir / relative_paths["rectified"]
            self._write_image(
                rectified_path,
                rectified_roi,
                [cv2.IMWRITE_PNG_COMPRESSION, self.png_compression],
            )
            created_paths.append(rectified_path)

            source_relative = relative_paths["source"]
            if source_relative is not None:
                source_path = self.session_dir / source_relative
                self._write_image(
                    source_path,
                    source_frame,
                    [
                        cv2.IMWRITE_JPEG_QUALITY,
                        self.source_jpeg_quality,
                    ],
                )
                created_paths.append(source_path)

            source_roi_relative = relative_paths["source_roi"]
            if source_roi_relative is not None:
                source_roi_path = self.session_dir / source_roi_relative
                self._write_image(
                    source_roi_path,
                    source_roi_frame,
                    [cv2.IMWRITE_PNG_COMPRESSION, self.png_compression],
                )
                created_paths.append(source_roi_path)

            label_relative = relative_paths["label"]
            if label_relative is not None:
                label_path = self.session_dir / label_relative
                if label_path.exists():
                    raise FileExistsError(f"拒绝覆盖标签：{label_path}")
                if yolo_box is None:
                    label_text = ""
                else:
                    label_text = (
                        "0 "
                        + " ".join(f"{value:.8f}" for value in yolo_box)
                        + "\n"
                    )
                label_path.write_text(label_text, encoding="utf-8")
                created_paths.append(label_path)

            record: dict[str, Any] = {
                "schema": "steel-ball-roi-sample/v1",
                "sample_id": sample_id,
                "index": index,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "captured_monotonic": float(captured_monotonic),
                "angle_deg": float(angle_deg),
                "label_state": label_state,
                "class_id": 0 if label_state == "positive" else None,
                "yolo_box_cxcywh": (
                    None if yolo_box is None else list(map(float, yolo_box))
                ),
                "paths": relative_paths,
                "rectified_size": {
                    "width": int(rectified_roi.shape[1]),
                    "height": int(rectified_roi.shape[0]),
                },
                "model_input_size": {
                    "width": int(model_input.shape[1]),
                    "height": int(model_input.shape[0]),
                },
                "source_roi_size": (
                    None
                    if source_roi_frame is None
                    else {
                        "width": int(source_roi_frame.shape[1]),
                        "height": int(source_roi_frame.shape[0]),
                    }
                ),
                "letterbox": letterbox_info.to_dict(),
            }
            if extra_metadata:
                record["rectification_state"] = extra_metadata
            self._records.append(record)
            self._write_metadata()
        except Exception:
            if self._records and self._records[-1].get("sample_id") == sample_id:
                self._records.pop()
            for path in reversed(created_paths):
                path.unlink(missing_ok=True)
            raise

        self._next_index += 1
        return SavedSample(
            sample_id=sample_id,
            label_state=label_state,
            record=record,
        )

    def undo_last(self) -> SavedSample | None:
        if not self._records:
            return None
        record = self._records.pop()
        for relative in record["paths"].values():
            if relative is not None:
                (self.session_dir / relative).unlink(missing_ok=True)
        self._next_index = int(record["index"])
        self._write_metadata()
        return SavedSample(
            sample_id=str(record["sample_id"]),
            label_state=record["label_state"],
            record=record,
        )

    def label_unlabeled(
        self,
        sample_id: str,
        *,
        label_state: Literal["positive", "negative"],
        yolo_box: tuple[float, float, float, float] | None = None,
    ) -> SavedSample:
        """Promote one captured frame into the training-ready pair."""

        if label_state not in ("positive", "negative"):
            raise ValueError("批量标注只能设置positive或negative")
        if label_state == "positive" and yolo_box is None:
            raise ValueError("有球样本必须提供YOLO钢球框")
        if label_state == "negative" and yolo_box is not None:
            raise ValueError("无球负样本不能提供YOLO钢球框")
        if yolo_box is not None and (
            len(yolo_box) != 4
            or not all(0.0 <= float(value) <= 1.0 for value in yolo_box)
        ):
            raise ValueError("YOLO钢球框必须包含4个[0,1]归一化数值")

        index = self._record_index(sample_id)
        original = copy.deepcopy(self._records[index])
        if original["label_state"] != "unlabeled":
            raise ValueError(f"样本已经标注：{sample_id}")

        source_relative = str(original["paths"]["model_input"])
        source_path = self.session_dir / source_relative
        image_relative = f"images/{sample_id}.png"
        image_path = self.session_dir / image_relative
        label_relative = f"labels/{sample_id}.txt"
        label_path = self.session_dir / label_relative
        temporary_label = self.session_dir / "labels" / f".{sample_id}.txt.tmp"
        if not source_path.is_file():
            raise FileNotFoundError(f"待标注图片不存在：{source_path}")
        if image_path.exists() or label_path.exists() or temporary_label.exists():
            raise FileExistsError(f"标注目标已经存在：{sample_id}")

        if yolo_box is None:
            label_text = ""
        else:
            label_text = (
                "0 "
                + " ".join(f"{float(value):.8f}" for value in yolo_box)
                + "\n"
            )

        moved = False
        label_created = False
        try:
            temporary_label.write_text(label_text, encoding="utf-8")
            temporary_label.replace(label_path)
            label_created = True
            source_path.replace(image_path)
            moved = True

            updated = copy.deepcopy(original)
            updated["label_state"] = label_state
            updated["class_id"] = 0 if label_state == "positive" else None
            updated["yolo_box_cxcywh"] = (
                None if yolo_box is None else list(map(float, yolo_box))
            )
            updated["paths"]["model_input"] = image_relative
            updated["paths"]["label"] = label_relative
            self._records[index] = updated
            self._write_metadata()
        except Exception:
            self._records[index] = original
            if moved and image_path.exists() and not source_path.exists():
                image_path.replace(source_path)
            if label_created:
                label_path.unlink(missing_ok=True)
            temporary_label.unlink(missing_ok=True)
            raise

        return SavedSample(
            sample_id=sample_id,
            label_state=label_state,
            record=copy.deepcopy(self._records[index]),
        )

    def reset_to_unlabeled(self, sample_id: str) -> SavedSample:
        """Return one batch-labelled sample to the annotation queue."""

        index = self._record_index(sample_id)
        original = copy.deepcopy(self._records[index])
        if original["label_state"] not in ("positive", "negative"):
            raise ValueError(f"样本不是已标注状态：{sample_id}")

        image_path = self.session_dir / str(original["paths"]["model_input"])
        label_path = self.session_dir / str(original["paths"]["label"])
        unlabeled_relative = f"unlabeled/{sample_id}.png"
        unlabeled_path = self.session_dir / unlabeled_relative
        if not image_path.is_file() or not label_path.is_file():
            raise FileNotFoundError(f"已标注样本文件不完整：{sample_id}")
        if unlabeled_path.exists():
            raise FileExistsError(f"未标注目标已经存在：{unlabeled_path}")

        label_text = label_path.read_text(encoding="utf-8")
        moved = False
        label_removed = False
        try:
            image_path.replace(unlabeled_path)
            moved = True
            label_path.unlink()
            label_removed = True

            updated = copy.deepcopy(original)
            updated["label_state"] = "unlabeled"
            updated["class_id"] = None
            updated["yolo_box_cxcywh"] = None
            updated["paths"]["model_input"] = unlabeled_relative
            updated["paths"]["label"] = None
            self._records[index] = updated
            self._write_metadata()
        except Exception:
            self._records[index] = original
            if moved and unlabeled_path.exists() and not image_path.exists():
                unlabeled_path.replace(image_path)
            if label_removed and not label_path.exists():
                label_path.write_text(label_text, encoding="utf-8")
            raise

        return SavedSample(
            sample_id=sample_id,
            label_state="unlabeled",
            record=copy.deepcopy(self._records[index]),
        )

    def _record_index(self, sample_id: str) -> int:
        for index, record in enumerate(self._records):
            if record["sample_id"] == sample_id:
                return index
        raise ValueError(f"找不到样本：{sample_id}")

    @staticmethod
    def _write_image(
        path: Path,
        image: np.ndarray,
        parameters: list[int],
    ) -> None:
        if path.exists():
            raise FileExistsError(f"拒绝覆盖图像：{path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), image, parameters):
            raise OSError(f"图像保存失败：{path}")

    def _write_metadata(self) -> None:
        temporary = self.session_dir / ".metadata.jsonl.tmp"
        text = "".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in self._records
        )
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self.metadata_path)
