"""键盘或文本文件提供的人工摆杆角度源。"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path


class ManualAngleError(ValueError):
    """人工角度输入无效。"""


@dataclass(slots=True)
class ManualAngleSource:
    """保存测试角度，并支持键盘微调或文本文件更新。"""

    angle_deg: float
    step_deg: float = 0.25
    minimum_deg: float = -90.0
    maximum_deg: float = 90.0
    _last_file_mtime_ns: int | None = field(default=None, init=False)

    # OpenCV waitKeyEx 在 Linux/Windows 常见的左右方向键编码。
    LEFT_KEYS = frozenset((ord("a"), ord("A"), 81, 2424832))
    RIGHT_KEYS = frozenset((ord("d"), ord("D"), 83, 2555904))
    ZERO_KEYS = frozenset((ord("0"), ord("z"), ord("Z")))

    def __post_init__(self) -> None:
        self.step_deg = float(self.step_deg)
        self.minimum_deg = float(self.minimum_deg)
        self.maximum_deg = float(self.maximum_deg)
        if not math.isfinite(self.step_deg) or self.step_deg <= 0:
            raise ManualAngleError("人工角度步长必须为正数")
        if not (
            math.isfinite(self.minimum_deg)
            and math.isfinite(self.maximum_deg)
            and self.minimum_deg < self.maximum_deg
        ):
            raise ManualAngleError("人工角度范围无效")
        self.set_angle(self.angle_deg)

    def set_angle(self, value: float) -> float:
        angle = float(value)
        if not math.isfinite(angle):
            raise ManualAngleError("人工角度必须是有限数值")
        if not self.minimum_deg <= angle <= self.maximum_deg:
            raise ManualAngleError(
                f"人工角度 {angle:+.3f}deg 超出 "
                f"{self.minimum_deg:+.3f}..{self.maximum_deg:+.3f}deg"
            )
        self.angle_deg = angle
        return angle

    def handle_key(self, key: int) -> bool:
        """处理 A/D、左右方向键和 0/Z；角度改变返回 True。"""

        if key in self.LEFT_KEYS:
            self.set_angle(max(self.minimum_deg, self.angle_deg - self.step_deg))
            return True
        if key in self.RIGHT_KEYS:
            self.set_angle(min(self.maximum_deg, self.angle_deg + self.step_deg))
            return True
        if key in self.ZERO_KEYS:
            self.set_angle(0.0)
            return True
        return False

    def refresh_file(self, path: str | Path) -> bool:
        """文件内容变化时读取其中唯一的浮点角度。"""

        angle_path = Path(path).expanduser()
        try:
            stat = angle_path.stat()
        except OSError as exc:
            raise ManualAngleError(f"无法读取人工角度文件：{angle_path}") from exc
        if self._last_file_mtime_ns == stat.st_mtime_ns:
            return False
        try:
            text = angle_path.read_text(encoding="utf-8").strip()
            angle = float(text)
        except (OSError, ValueError) as exc:
            raise ManualAngleError(
                f"人工角度文件必须只包含一个数字：{angle_path}"
            ) from exc
        self.set_angle(angle)
        self._last_file_mtime_ns = stat.st_mtime_ns
        return True
