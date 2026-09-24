"""Optional native NCNN backend and Ultralytics-compatible result adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import cv2
import numpy as np

try:
    from ._ncnn_cpp import NcnnBackend as _NativeNcnnBackend
except ImportError as exc:  # pragma: no cover - depends on the local C++ build
    _NativeNcnnBackend = None
    _NATIVE_IMPORT_ERROR: Exception | None = exc
else:
    _NATIVE_IMPORT_ERROR = None


@dataclass(frozen=True, slots=True)
class NativeNcnnTimings:
    model_load_ms: float = 0.0
    preprocess_ms: float = 0.0
    inference_ms: float = 0.0
    postprocess_ms: float = 0.0


class _Boxes:
    def __init__(self, data: np.ndarray) -> None:
        values = np.asarray(data, dtype=np.float32).reshape(-1, 6)
        self.xyxy = values[:, :4]
        self.conf = values[:, 4]
        self.cls = values[:, 5]

    def __len__(self) -> int:
        return len(self.xyxy)


def native_ncnn_available() -> bool:
    """Return whether the compiled pybind11/NCNN extension is importable."""

    return _NativeNcnnBackend is not None


def native_ncnn_import_error() -> str | None:
    """Return the native import failure text for actionable diagnostics."""

    return None if _NATIVE_IMPORT_ERROR is None else str(_NATIVE_IMPORT_ERROR)


ImageSize = int | tuple[int, int]


def _normalize_image_size(image_size: int | Sequence[int]) -> tuple[int, int]:
    if isinstance(image_size, bool):
        raise ValueError("imgsz must be a positive integer or (height, width)")
    if isinstance(image_size, int):
        height = width = int(image_size)
    elif len(image_size) == 2:
        height, width = (int(value) for value in image_size)
    else:
        raise ValueError("imgsz must be a positive integer or (height, width)")
    if height <= 0 or width <= 0:
        raise ValueError("imgsz dimensions must be positive")
    return height, width


def _letterbox(
    frame: np.ndarray,
    image_size: int | Sequence[int],
) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Match Ultralytics' centered padding for square or rectangular input."""

    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    height, width = frame.shape[:2]
    target_height, target_width = _normalize_image_size(image_size)
    ratio = min(
        target_width / max(1, width),
        target_height / max(1, height),
    )
    resized_width = max(1, int(round(width * ratio)))
    resized_height = max(1, int(round(height * ratio)))
    if (resized_width, resized_height) == (width, height):
        resized = frame
    else:
        resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    pad_width = target_width - resized_width
    pad_height = target_height - resized_height
    left = int(round(pad_width / 2.0 - 0.1))
    right = pad_width - left
    top = int(round(pad_height / 2.0 - 0.1))
    bottom = pad_height - top
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
    return np.ascontiguousarray(padded), ratio, (float(left), float(top))


class CppNcnnBackend:
    """Native NCNN inference with the result shape expected by the adaptive detector."""

    def __init__(self, model_path: str | Path, *, threads: int = 2) -> None:
        if _NativeNcnnBackend is None:
            detail = f": {_NATIVE_IMPORT_ERROR}" if _NATIVE_IMPORT_ERROR else ""
            raise RuntimeError(
                "The optional _ncnn_cpp extension is not built" + detail
                + ". Build it with cpp/build.ps1."
            )
        path = Path(model_path)
        if not path.is_dir():
            raise FileNotFoundError(f"NCNN model directory not found: {path}")
        if not (path / "model.ncnn.param").exists() or not (path / "model.ncnn.bin").exists():
            raise FileNotFoundError(f"NCNN model must contain model.ncnn.param and model.ncnn.bin: {path}")
        self.model_path = path
        self._native = _NativeNcnnBackend(str(path), int(threads))

    def predict(
        self,
        *,
        source: np.ndarray,
        imgsz: int | Sequence[int],
        conf: float,
        iou: float,
        classes: list[int] | None = None,
        max_det: int = 300,
        verbose: bool = False,
        **_: Any,
    ) -> list[SimpleNamespace]:
        del verbose
        if classes is not None and 0 not in classes:
            return [SimpleNamespace(boxes=_Boxes(np.empty((0, 6), dtype=np.float32)), timings=NativeNcnnTimings())]
        image_size = _normalize_image_size(imgsz)
        letterbox_started = cv2.getTickCount()
        padded, ratio, (pad_x, pad_y) = _letterbox(np.asarray(source), image_size)
        letterbox_ms = (cv2.getTickCount() - letterbox_started) * 1000.0 / cv2.getTickFrequency()
        values = self._native.infer(padded, float(conf), float(iou), int(max_det))
        model_values = np.asarray(values["boxes"], dtype=np.float32).reshape(-1, 6)
        if len(model_values):
            boxes = model_values[:, :4].copy()
            boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pad_x) / ratio
            boxes[:, [1, 3]] = (boxes[:, [1, 3]] - pad_y) / ratio
            height, width = np.asarray(source).shape[:2]
            boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0.0, float(width))
            boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0.0, float(height))
            model_values[:, :4] = boxes
        native_timings = NativeNcnnTimings(
            model_load_ms=float(values.get("model_load_ms", 0.0)),
            preprocess_ms=letterbox_ms + float(values.get("preprocess_ms", 0.0)),
            inference_ms=float(values.get("inference_ms", 0.0)),
            postprocess_ms=float(values.get("postprocess_ms", 0.0)),
        )
        return [SimpleNamespace(boxes=_Boxes(model_values), timings=native_timings)]


__all__ = [
    "CppNcnnBackend",
    "NativeNcnnTimings",
    "native_ncnn_available",
    "native_ncnn_import_error",
]
