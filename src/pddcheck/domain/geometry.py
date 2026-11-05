"""几何：像素矩形（左闭右开）、点空间几何与坐标映射（契约 §3.3/§3.4）。

舍入规则（契约 §3.4，迁移不得混用）：
- ``half_up=True``：正数 round-half-up，``int(f * W + 0.5)``，等同旧 ``frac_x/frac_y``
  的配置比例点规则；
- ``half_up=False``：变换后 ``int()`` 截断，等同旧 matcher 输出规则。

``rotation != 0`` 的映射属 T06/T07 范围，本版显式拒绝，不悄悄给错值。
"""

from __future__ import annotations

from dataclasses import dataclass

from pddcheck.domain.errors import InvalidDomain
from pddcheck.domain.jsonio import serializable, strict_fields
from pddcheck.domain.validate import require_int

_ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True, slots=True)
@serializable
class Rect:
    """像素矩形，左闭右开；w/h >= 1。"""

    x: int
    y: int
    w: int
    h: int

    def __post_init__(self) -> None:
        require_int(self.x, "Rect.x", minimum=0)
        require_int(self.y, "Rect.y", minimum=0)
        require_int(self.w, "Rect.w", minimum=1)
        require_int(self.h, "Rect.h", minimum=1)

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    def center_floor(self) -> tuple[int, int]:
        """整型中心（向下取整）；仅供诊断展示，动作锚点走候选自己的 tap_point。"""
        return (self.x + self.w // 2, self.y + self.h // 2)

    @classmethod
    def from_jsonable(cls, data: dict) -> "Rect":
        return cls(**strict_fields(cls, data))


@dataclass(frozen=True, slots=True)
@serializable
class Geometry:
    """一块屏的几何与版本号；revision 变化即旧坐标令牌失效（契约 §3.3）。"""

    image_width: int
    image_height: int
    tap_width: int
    tap_height: int
    rotation: int
    revision: int
    display_id: int | None = None

    def __post_init__(self) -> None:
        require_int(self.image_width, "Geometry.image_width", minimum=1)
        require_int(self.image_height, "Geometry.image_height", minimum=1)
        require_int(self.tap_width, "Geometry.tap_width", minimum=1)
        require_int(self.tap_height, "Geometry.tap_height", minimum=1)
        require_int(self.revision, "Geometry.revision", minimum=0)
        if self.rotation not in _ROTATIONS:
            raise InvalidDomain(f"Geometry.rotation 必须在 {_ROTATIONS}，得到 {self.rotation}")
        if self.display_id is not None:
            require_int(self.display_id, "Geometry.display_id", minimum=0)

    def scale_to_tap(self, px: int, py: int, *, half_up: bool) -> tuple[int, int]:
        """截图空间 → 点空间。两种舍入分别对齐旧 frac / matcher 规则。"""
        require_int(px, "px", minimum=0)
        require_int(py, "py", minimum=0)
        if self.rotation != 0:
            raise InvalidDomain("rotation != 0 的坐标映射未实现（T06/T07 范围），拒绝猜")
        if px >= self.image_width or py >= self.image_height:
            raise InvalidDomain(f"坐标越界：({px},{py}) 不在 {self.image_width}x{self.image_height} 内")
        fx = px * self.tap_width / self.image_width
        fy = py * self.tap_height / self.image_height
        if half_up:
            return int(fx + 0.5), int(fy + 0.5)
        return int(fx), int(fy)

    @classmethod
    def from_jsonable(cls, data: dict) -> "Geometry":
        return cls(**strict_fields(cls, data))
