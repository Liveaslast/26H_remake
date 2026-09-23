"""OpenCV 检测结果可视化。"""

from __future__ import annotations

import cv2
import numpy as np

from .models import FrameDetection


def draw_detections(
    frame: np.ndarray,
    detection: FrameDetection,
    *,
    fps: float | None = None,
) -> np.ndarray:
    """在原图副本上绘制检测框、拟合圆、圆心和性能信息。"""

    if frame.ndim == 2:
        output = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    else:
        output = frame.copy()

    for index, ball in enumerate(detection.balls, start=1):
        x1, y1, x2, y2 = (int(round(value)) for value in ball.box_xyxy)
        center = tuple(int(round(value)) for value in ball.center_px)
        radius = max(1, int(round(ball.radius_px)))
        if ball.source == "ransac":
            cv2.circle(output, center, radius, (0, 210, 0), 2, cv2.LINE_AA)
            color = (0, 210, 0)
        else:
            cv2.rectangle(output, (x1, y1), (x2, y2), (0, 215, 255), 2)
            color = (0, 215, 255)
        cv2.drawMarker(output, center, (0, 0, 255), cv2.MARKER_CROSS, 14, 2)
        label = f"#{index} {ball.confidence:.2f} {ball.source}"
        cv2.putText(
            output,
            label,
            (x1, max(18, y1 - 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )

    status = (
        f"Balls: {detection.count}  inference: {detection.inference_ms:.1f} ms  "
        f"refine: {detection.refinement_ms:.1f} ms"
    )
    if fps is not None:
        status += f"  FPS: {fps:.1f}"
    cv2.rectangle(output, (0, 0), (min(output.shape[1], 760), 34), (0, 0, 0), -1)
    cv2.putText(
        output,
        status,
        (10, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return output
