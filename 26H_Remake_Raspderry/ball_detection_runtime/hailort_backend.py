"""Native HailoRT backend with lightweight YOLO head decoding."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import cv2
import numpy as np

from .ncnn_backend import _letterbox, _normalize_image_size


@dataclass(frozen=True, slots=True)
class HailoRtTimings:
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


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-values))


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float, max_det: int) -> np.ndarray:
    if len(boxes) == 0:
        return np.empty((0,), dtype=np.int64)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while len(order) and len(keep) < max_det:
        index = int(order[0])
        keep.append(index)
        if len(order) == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[index, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[index, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[index, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[index, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area0 = np.maximum(0.0, boxes[index, 2] - boxes[index, 0]) * np.maximum(0.0, boxes[index, 3] - boxes[index, 1])
        area1 = np.maximum(0.0, boxes[rest, 2] - boxes[rest, 0]) * np.maximum(0.0, boxes[rest, 3] - boxes[rest, 1])
        iou = inter / np.maximum(area0 + area1 - inter, 1e-6)
        order = rest[iou <= iou_threshold]
    return np.asarray(keep, dtype=np.int64)


def _as_hwc(value: Any) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim == 4 and array.shape[0] == 1:
        array = array[0]
    if array.ndim != 3:
        raise ValueError(f"Unexpected Hailo output rank: shape={array.shape}")
    return array.astype(np.float32, copy=False)


class NativeHailoRtBackend:
    """Direct HailoRT inference.

    This backend expects the exported HEF to expose three box heads with four
    channels and matching one-class score heads, like:
    ``16x80x4 + 16x80x1``, ``8x40x4 + 8x40x1``, ``4x20x4 + 4x20x1``.
    """

    def __init__(self, model_path: str | Path) -> None:
        path = Path(model_path)
        if path.is_file() and path.suffix == ".hef":
            hef_path = path
        elif path.is_dir():
            candidates = sorted(path.glob("*.hef"))
            if not candidates:
                raise FileNotFoundError(f"Hailo model directory must contain a .hef file: {path}")
            hef_path = candidates[0]
        else:
            raise FileNotFoundError(f"Hailo model path not found: {path}")

        try:
            from hailo_platform import (
                ConfigureParams,
                FormatType,
                HEF,
                HailoStreamInterface,
                InferVStreams,
                InputVStreamParams,
                OutputVStreamParams,
                VDevice,
            )
        except ImportError as exc:
            raise RuntimeError("Install HailoRT Python bindings in the active environment") from exc

        tick = cv2.getTickCount()
        self.model_path = path
        self.hef_path = hef_path
        self._hef = HEF(str(hef_path))
        self._target = VDevice()
        configure_params = ConfigureParams.create_from_hef(
            self._hef,
            interface=HailoStreamInterface.PCIe,
        )
        self._network_group = self._target.configure(self._hef, configure_params)[0]
        self._network_group_params = self._network_group.create_params()
        self._input_params = InputVStreamParams.make(
            self._network_group,
            format_type=FormatType.UINT8,
        )
        self._output_params = OutputVStreamParams.make(
            self._network_group,
            format_type=FormatType.FLOAT32,
        )
        self._infer = InferVStreams(
            self._network_group,
            self._input_params,
            self._output_params,
        )
        self._activation = self._network_group.activate(self._network_group_params)
        self._activation.__enter__()
        self._infer.__enter__()
        self._input_name = self._hef.get_input_vstream_infos()[0].name
        self._output_names = [info.name for info in self._hef.get_output_vstream_infos()]
        self._load_ms = (cv2.getTickCount() - tick) * 1000.0 / cv2.getTickFrequency()
        self._debug_once = os.environ.get("HAILORT_BACKEND_DEBUG", "0") == "1"

    def __del__(self) -> None:
        for attr in ("_infer", "_activation", "_target"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            try:
                if attr in ("_infer", "_activation"):
                    obj.__exit__(None, None, None)
                else:
                    obj.release()
            except Exception:
                pass

    @staticmethod
    def _score_values(raw_scores: np.ndarray) -> np.ndarray:
        scores = raw_scores.reshape(-1).astype(np.float32, copy=False)
        if len(scores) and (float(np.nanmin(scores)) < 0.0 or float(np.nanmax(scores)) > 1.0):
            scores = _sigmoid(scores)
        return scores

    @staticmethod
    def _decode_boxes(
        raw_boxes: np.ndarray,
        *,
        grid_h: int,
        grid_w: int,
        input_h: int,
        input_w: int,
    ) -> np.ndarray:
        values = raw_boxes.reshape(-1, 4).astype(np.float32, copy=False)
        yy, xx = np.meshgrid(np.arange(grid_h, dtype=np.float32), np.arange(grid_w, dtype=np.float32), indexing="ij")
        centers_x = (xx.reshape(-1) + 0.5) * (input_w / grid_w)
        centers_y = (yy.reshape(-1) + 0.5) * (input_h / grid_h)
        stride_x = input_w / grid_w
        stride_y = input_h / grid_h

        mode = os.environ.get("HAILORT_BOX_FORMAT", "ltrb_stride").lower()
        if mode == "xywh_norm":
            cx = values[:, 0] * input_w
            cy = values[:, 1] * input_h
            bw = values[:, 2] * input_w
            bh = values[:, 3] * input_h
            return np.stack((cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2), axis=1)
        if mode == "xywh_pixel":
            cx, cy, bw, bh = values[:, 0], values[:, 1], values[:, 2], values[:, 3]
            return np.stack((cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2), axis=1)
        if mode == "xyxy_pixel":
            return values.copy()

        # Default: YOLO-style left/top/right/bottom distances in grid units.
        left = values[:, 0] * stride_x
        top = values[:, 1] * stride_y
        right = values[:, 2] * stride_x
        bottom = values[:, 3] * stride_y
        return np.stack((centers_x - left, centers_y - top, centers_x + right, centers_y + bottom), axis=1)

    def _decode(
        self,
        outputs: dict[str, Any],
        *,
        conf: float,
        iou: float,
        max_det: int,
        source_shape: tuple[int, int],
        input_shape: tuple[int, int],
        ratio: float,
        pad_x: float,
        pad_y: float,
    ) -> np.ndarray:
        heads: dict[tuple[int, int], dict[str, np.ndarray]] = {}
        for name, value in outputs.items():
            array = _as_hwc(value)
            key = (int(array.shape[0]), int(array.shape[1]))
            heads.setdefault(key, {})
            if int(array.shape[2]) == 4:
                heads[key]["boxes"] = array
            elif int(array.shape[2]) == 1:
                heads[key]["scores"] = array

        all_boxes: list[np.ndarray] = []
        all_scores: list[np.ndarray] = []
        input_h, input_w = input_shape
        for (grid_h, grid_w), pair in sorted(heads.items(), reverse=True):
            if "boxes" not in pair or "scores" not in pair:
                continue
            scores = self._score_values(pair["scores"])
            keep = scores >= conf
            if not np.any(keep):
                continue
            boxes = self._decode_boxes(pair["boxes"], grid_h=grid_h, grid_w=grid_w, input_h=input_h, input_w=input_w)
            all_boxes.append(boxes[keep])
            all_scores.append(scores[keep])

        if not all_boxes:
            return np.empty((0, 6), dtype=np.float32)

        boxes = np.concatenate(all_boxes, axis=0)
        scores = np.concatenate(all_scores, axis=0)
        boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pad_x) / max(ratio, 1e-6)
        boxes[:, [1, 3]] = (boxes[:, [1, 3]] - pad_y) / max(ratio, 1e-6)
        source_h, source_w = source_shape
        boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0.0, float(source_w))
        boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0.0, float(source_h))
        valid = (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
        boxes, scores = boxes[valid], scores[valid]
        keep_indices = _nms(boxes, scores, iou, max_det)
        boxes, scores = boxes[keep_indices], scores[keep_indices]
        classes = np.zeros((len(boxes), 1), dtype=np.float32)
        return np.concatenate((boxes, scores.reshape(-1, 1), classes), axis=1).astype(np.float32, copy=False)

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
            return [SimpleNamespace(boxes=_Boxes(np.empty((0, 6), dtype=np.float32)), timings=HailoRtTimings())]
        image_size = _normalize_image_size(imgsz)
        source_array = np.asarray(source)
        t0 = cv2.getTickCount()
        padded, ratio, (pad_x, pad_y) = _letterbox(source_array, image_size)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        batched = np.expand_dims(np.ascontiguousarray(rgb, dtype=np.uint8), axis=0)
        preprocess_ms = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()

        t1 = cv2.getTickCount()
        outputs = self._infer.infer({self._input_name: batched})
        inference_ms = (cv2.getTickCount() - t1) * 1000.0 / cv2.getTickFrequency()

        t2 = cv2.getTickCount()
        values = self._decode(
            outputs,
            conf=float(conf),
            iou=float(iou),
            max_det=int(max_det),
            source_shape=source_array.shape[:2],
            input_shape=image_size,
            ratio=float(ratio),
            pad_x=float(pad_x),
            pad_y=float(pad_y),
        )
        if self._debug_once:
            self._debug_once = False
            print(
                "HailoRT outputs: "
                + ", ".join(f"{name}:{np.asarray(value).shape}" for name, value in outputs.items())
                + f"; decoded={len(values)}; box_format={os.environ.get('HAILORT_BOX_FORMAT', 'ltrb_stride')}",
                flush=True,
            )
        postprocess_ms = (cv2.getTickCount() - t2) * 1000.0 / cv2.getTickFrequency()
        timings = HailoRtTimings(
            model_load_ms=self._load_ms,
            preprocess_ms=preprocess_ms,
            inference_ms=inference_ms,
            postprocess_ms=postprocess_ms,
        )
        self._load_ms = 0.0
        return [SimpleNamespace(boxes=_Boxes(values), timings=timings)]


__all__ = ["NativeHailoRtBackend", "HailoRtTimings"]
