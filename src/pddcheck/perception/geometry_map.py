"""几何映射：旧 %.5f 缩放与 emit 截断（契约 §3.4 的第二类舍入）。"""

from __future__ import annotations


def scale_5dp(tap_side: int, image_side: int) -> float:
    """图像空间 → 点空间的缩放，**保留 5 位小数**（旧 png_scale 的 awk %.5f，
    band/pill 的 bsx/bsy 同式）。5 位小数本身就是旧行为的一部分，不要换成全精度。"""
    if image_side <= 0:
        raise ValueError("image_side 必须 > 0")
    return float(f"{tap_side / image_side:.5f}")


def emit_point(px: float, py: float, scale_x: float, scale_y: float,
               offset_x: float = 0.0, offset_y: float = 0.0) -> tuple[int, int]:
    """旧 emit()：int(x*SX+OX)——正数截断（int()），不是 round。"""
    return int(px * scale_x + offset_x), int(py * scale_y + offset_y)
