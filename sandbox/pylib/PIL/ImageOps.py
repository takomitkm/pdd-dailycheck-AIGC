# -*- coding: utf-8 -*-
"""PIL 兼容层的 ImageOps：只实现 pdd.sh 用到的 invert / autocontrast。"""
from .Image import Image


def invert(image):
    rows = image._px()
    if image.mode == "L":
        out = [bytes(255 - v for v in row) for row in rows]
        return Image("L", image.size, out)
    if image.mode == "RGB":
        out = []
        for row in rows:
            rgb = bytearray(len(row))
            for i in range(0, len(row), 3):
                rgb[i] = 255 - row[i]
                rgb[i + 1] = 255 - row[i + 1]
                rgb[i + 2] = 255 - row[i + 2]
            out.append(rgb)
        return Image("RGB", image.size, out)
    raise NotImplementedError("invert() 只支持 L/RGB 模式")


def autocontrast(image, cutoff=0, ignore=None):
    """灰度图对比度拉伸：两端各剪掉 cutoff% 像素后把 [lo,hi] 映到 [0,255]。

    剪完 lo>=hi（比如纯色图）时保持原图不动，与 Pillow 的行为一致。
    """
    if image.mode != "L":
        raise NotImplementedError("autocontrast() 只支持 L 模式")
    if isinstance(cutoff, tuple):
        cut_lo, cut_hi = cutoff
    else:
        cut_lo = cut_hi = cutoff
    rows = image._px()
    hist = [0] * 256
    for row in rows:
        for v in row:
            hist[v] += 1
    n = len(rows) * rows[0].__len__()
    lo, hi = 0, 255
    if cut_lo:
        cut = cut_lo * n // 100
        acc = 0
        while lo < 255 and acc + hist[lo] <= cut:
            acc += hist[lo]
            lo += 1
    if cut_hi:
        cut = cut_hi * n // 100
        acc = 0
        while hi > 0 and acc + hist[hi] <= cut:
            acc += hist[hi]
            hi -= 1
    if lo >= hi:
        return Image("L", image.size, [bytes(row) for row in rows])
    span = hi - lo
    lut = [(i - lo) * 255 // span if i > lo else 0 for i in range(256)]
    for i in range(256):
        if i < lo:
            lut[i] = 0
        elif i > hi:
            lut[i] = 255
    out = [bytes(lut[v] for v in row) for row in rows]
    return Image("L", image.size, out)
