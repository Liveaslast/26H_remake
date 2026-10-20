"""Backend-independent image sizing and centered letterbox preprocessing."""

from typing import Sequence

import cv2
import numpy as np


def normalize_image_size(image_size: int | Sequence[int]) -> tuple[int, int]:
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


def letterbox(
    frame: np.ndarray,
    image_size: int | Sequence[int],
) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Match Ultralytics' centered padding for square or rectangular input."""

    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    height, width = frame.shape[:2]
    target_height, target_width = normalize_image_size(image_size)
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
