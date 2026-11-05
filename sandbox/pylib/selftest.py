#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PIL 兼容层自检：造图→读→裁→换→存→再读，坏输入必须抛错。

在沙箱铺装时由 runner 调用（SBX_PYLIB 自检），全过打印 SELFTEST_PIL_OK，
任何一项不过都以非零退出 —— 兼容层坏了，band/pill 那几个用例的红就是假的。
"""
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageOps  # noqa: E402

fails = []


def check(name, cond):
    print("%-46s %s" % (name, "ok" if cond else "FAIL"))
    if not cond:
        fails.append(name)


def chunk(t, b):
    return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)


def _paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a); pb = abs(p - b); pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def pattern_png(w, h, colortype=2):
    """带滤波（0..4 轮转）的渐变 PNG，专测反滤波各支路。"""
    bpp = {0: 1, 2: 3, 6: 4}[colortype]
    stride = w * bpp
    raw = bytearray()
    prev = bytes(stride)
    for y in range(h):
        row = bytearray(stride)
        for x in range(w):
            for c in range(bpp):
                row[x * bpp + c] = (x * 7 + y * 3 + c * 11) & 0xFF
        f = y % 5 if colortype == 2 else 0
        enc = bytearray(stride)
        for i in range(stride):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c2 = prev[i - bpp] if i >= bpp else 0
            if f == 0:
                enc[i] = row[i]
            elif f == 1:
                enc[i] = (row[i] - a) & 0xFF
            elif f == 2:
                enc[i] = (row[i] - b) & 0xFF
            elif f == 3:
                enc[i] = (row[i] - ((a + b) >> 1)) & 0xFF
            else:
                enc[i] = (row[i] - _paeth(a, b, c2)) & 0xFF
        raw.append(f)
        raw += enc
        prev = bytes(row)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, colortype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw)))
            + chunk(b"IEND", b""))


def rows_of(im):
    return [bytes(r) for r in im._px()]


def main():
    tmp = os.environ.get("TMPDIR", "/tmp")
    p1 = os.path.join(tmp, "sbx-pil-selftest-1.png")

    # 1) new() -> save -> open：基本往返
    im = Image.new("RGB", (720, 1280), (200, 30, 40))
    check("new/save/open 尺寸", (im.size == (720, 1280)))
    im.save(p1)
    im2 = Image.open(p1)
    check("open 惰性：size 不解码", im2.size == (720, 1280) and im2.mode == "RGB")
    check("open 往返像素一致", rows_of(im2) == rows_of(im))
    os.unlink(p1)

    # 2) 带滤波 0..4 的 PNG 反滤波
    for ct in (0, 2, 6):
        data = pattern_png(17, 13, ct)
        with _tmpfile(data) as pf:
            im3 = Image.open(pf)
            ok = im3.size == (17, 13)
            px = rows_of(im3)
            ok = ok and px[3][ (7 * len(px[0]) // 17) ] >= 0 and len(px) == 13
            # 渐变规律抽查：(x=7,y=3) 通道值
            bpp = {0: 1, 2: 3, 6: 4}[ct]
            i = 7 * bpp
            want = tuple((7 * 7 + 3 * 3 + c * 11) & 0xFF for c in range(bpp))
            got = tuple(px[3][i:i + bpp])
            check("滤波反解 colortype=%d" % ct, ok and got == want)

    # 3) crop / convert / point / invert / autocontrast
    im4 = Image.new("RGB", (300, 200), (200, 30, 40))
    c = im4.crop((10, 20, 260, 180))
    check("crop 尺寸", c.size == (250, 160))
    g = c.convert("L")
    check("convert L 数值", g.size == (250, 160)
          and rows_of(g)[0][0] == (200 * 299 + 30 * 587 + 40 * 114) // 1000)
    inv = ImageOps.invert(g)
    check("invert", rows_of(inv)[0][0] == 255 - (200 * 299 + 30 * 587 + 40 * 114) // 1000)
    ac = ImageOps.autocontrast(g, cutoff=1)
    check("autocontrast 纯色图保持原样", rows_of(ac) == rows_of(g))
    th = g.point(lambda v: 0 if v < 128 else 255)
    check("point 阈值", rows_of(th)[0][0] == 0)
    t0 = time.time()
    big = Image.new("RGB", (720, 1280), (90, 130, 170))
    band = big.crop((0, 380, 720, 500)).convert("L").point(lambda v: v)
    up = band.resize((2160, 360), Image.LANCZOS)
    dt = time.time() - t0
    check("LANCZOS x3 band 裁片尺寸", up.size == (2160, 360))
    print("%-46s %.2fs" % ("LANCZOS 720x120 -> 2160x360 耗时", dt))
    ni = Image.new("L", (100, 80), 5).resize((151, 120), Image.LANCZOS)
    check("非整数比例 resize", ni.size == (151, 120))
    nn = Image.new("L", (50, 40), 9).resize((25, 20), Image.NEAREST)
    check("NEAREST resize", nn.size == (25, 20) and rows_of(nn)[0][0] == 9)

    # 4) 坏输入必须抛错
    for name, probe_pixels, data in (
        ("坏签名拒绝", False, b"NOTPNG" + b"\x00" * 64),
        ("截断 IDAT 拒绝（像素访问时）", True,
         b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
         + chunk(b"IDAT", b"\x00\x01")),
    ):
        try:
            with _tmpfile(data) as pf:
                bad = Image.open(pf)
                if probe_pixels:
                    rows_of(bad)   # 头能过，像素必须炸
            check(name, False)
        except ValueError:
            check(name, True)
        except Exception:
            check(name, False)

    print()
    if fails:
        print("SELFTEST_PIL_FAIL: %s" % ", ".join(fails))
        return 1
    print("SELFTEST_PIL_OK")
    return 0


class _tmpfile:
    def __init__(self, data):
        import tempfile
        self.fd, self.path = tempfile.mkstemp(dir=os.environ.get("TMPDIR", "/tmp"),
                                              suffix=".png")
        with os.fdopen(self.fd, "wb") as f:
            f.write(data)

    def __enter__(self):
        return self.path

    def __exit__(self, *a):
        os.unlink(self.path)
        return False


if __name__ == "__main__":
    sys.exit(main())
