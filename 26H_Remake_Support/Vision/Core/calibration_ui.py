"""正式标定和无M0标定共用的交互选点与预览工具。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class PointSelection:
    image_points: tuple[tuple[float, float], ...]


def parse_number_list(text: str, name: str) -> list[float]:
    try:
        values = [float(part.strip()) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} 必须是逗号分隔的数字") from exc
    if not values:
        raise argparse.ArgumentTypeError(f"{name} 不能为空")
    if not np.isfinite(values).all():
        raise argparse.ArgumentTypeError(f"{name} 必须是有限数值")
    return values


def _scaled_for_display(
    image: np.ndarray,
    maximum_width: int,
    maximum_height: int,
) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    scale = min(
        1.0,
        maximum_width / float(width),
        maximum_height / float(height),
    )
    if scale >= 0.999:
        return image.copy(), 1.0
    displayed = cv2.resize(
        image,
        (int(round(width * scale)), int(round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return displayed, scale


def select_points(
    image: np.ndarray,
    *,
    window_name: str,
    labels: Sequence[str],
    maximum_width: int,
    maximum_height: int,
) -> PointSelection:
    """鼠标左键依次选点，右键/Backspace 撤销，Enter 确认。"""

    points: list[tuple[float, float]] = []
    base, scale = _scaled_for_display(
        image,
        maximum_width,
        maximum_height,
    )

    def on_mouse(event: int, x: int, y: int, flags: int, userdata) -> None:
        del flags, userdata
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < len(labels):
            points.append((x / scale, y / scale))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()

    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(window_name, on_mouse)
    print(
        f"{window_name}: 左键依次点击；右键或 Backspace 撤销；"
        "R 重选；Enter 确认；Q 退出。",
        flush=True,
    )

    while True:
        canvas = base.copy()
        for index, point in enumerate(points):
            shown = (
                int(round(point[0] * scale)),
                int(round(point[1] * scale)),
            )
            cv2.circle(canvas, shown, 5, (0, 0, 255), -1, cv2.LINE_AA)
            cv2.putText(
                canvas,
                labels[index],
                (shown[0] + 8, max(18, shown[1] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
        next_label = (
            labels[len(points)] if len(points) < len(labels) else "press ENTER"
        )
        cv2.setWindowTitle(
            window_name,
            f"{window_name} - Next: {next_label} ({len(points)}/{len(labels)})",
        )
        cv2.imshow(window_name, canvas)
        key = cv2.waitKeyEx(20)
        if key in (ord("q"), ord("Q"), 27):
            cv2.destroyWindow(window_name)
            raise KeyboardInterrupt
        if key in (ord("r"), ord("R")):
            points.clear()
        elif key in (8, 127) and points:
            points.pop()
        elif key in (10, 13) and len(points) == len(labels):
            cv2.destroyWindow(window_name)
            return PointSelection(tuple(points))


def draw_source_preview(
    frame: np.ndarray,
    corners: np.ndarray,
    angle_deg: float,
) -> np.ndarray:
    preview = frame.copy()
    polygon = np.round(corners).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(preview, [polygon], True, (0, 255, 0), 2, cv2.LINE_AA)
    cv2.putText(
        preview,
        f"actual_angle={angle_deg:+.3f}deg",
        (12, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    return preview


def draw_rectified_preview(
    rectified: np.ndarray,
    points: Sequence[tuple[float, float]],
    positions: Sequence[float],
) -> np.ndarray:
    preview = rectified.copy()
    for point, position in zip(points, positions):
        u = int(round(point[0]))
        cv2.line(
            preview,
            (u, 0),
            (u, preview.shape[0] - 1),
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            preview,
            f"{position:+g}cm",
            (u + 4, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    return preview
