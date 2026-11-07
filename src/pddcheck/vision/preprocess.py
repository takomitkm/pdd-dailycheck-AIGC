"""band/pill 预处理（T06/T07）：与旧 band_pass/pill_pass 逐条对齐，可配缓存。

PIL 惰性导入（Windows 主 venv 无 Pillow 时，用 tests 里的 compat 层或跳过）。
预处理函数接收已解码的 PIL 图像对象（Image），返回新图像，便于缓存句柄复用。
"""

from __future__ import annotations


def band_crop_box(region: tuple[float, float, float, float], img_w: int, img_h: int,
                  pad_x: float = 0.02, pad_y: float = 0.015) -> tuple[int, int, int, int]:
    """旧 band_pass 几何：REGION 比例 ± pad，int 截断并夹到图内（返回 x0,y0,w,h）。"""
    x1, y1, x2, y2 = region
    x0 = max(0, int((x1 - pad_x) * img_w))
    xb = min(img_w, int((x2 + pad_x) * img_w))
    y0 = max(0, int((y1 - pad_y) * img_h))
    yb = min(img_h, int((y2 + pad_y) * img_h))
    return x0, y0, xb - x0, yb - y0


def pill_crop_box(pill: tuple[float, float, float, float], img_w: int, img_h: int
                  ) -> tuple[int, int, int, int]:
    """旧 pill_pass 几何：PILL 比例、不补 pad。"""
    x1, y1, x2, y2 = pill
    xa = max(0, int(x1 * img_w))
    ya = max(0, int(y1 * img_h))
    xb = min(img_w, int(x2 * img_w))
    yb = min(img_h, int(y2 * img_h))
    return xa, ya, xb - xa, yb - ya


def preprocess_band(im, box: tuple[int, int, int, int], scale: int, cutoff: int):
    """crop → 灰度 → autocontrast(cutoff) → ×scale（LANCZOS）。"""
    from PIL import Image, ImageOps
    x, y, w, h = box
    g = im.crop((x, y, x + w, y + h)).convert("L")
    g = ImageOps.autocontrast(g, cutoff=int(cutoff))
    if scale > 1:
        g = g.resize((g.width * scale, g.height * scale), Image.LANCZOS)
    return g


def preprocess_pill(im, box: tuple[int, int, int, int], div: int, th: int, mode: str):
    """crop → (inv: 灰度+反色+硬阈值 th | color: 原样) → ×div（LANCZOS）。"""
    from PIL import Image, ImageOps
    x, y, w, h = box
    g = im.crop((x, y, x + w, y + h))
    if mode != "color":
        g = ImageOps.invert(g.convert("L")).point(lambda v: 0 if v < th else 255)
    if div > 1:
        g = g.resize((g.width * div, g.height * div), Image.LANCZOS)
    return g


def recipe_tag(**kw) -> str:
    """把 recipe 参数拼成稳定字符串（进缓存键）。"""
    return ";".join(f"{k}={kw[k]}" for k in sorted(kw))
