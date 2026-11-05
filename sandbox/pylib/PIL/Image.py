# -*- coding: utf-8 -*-
"""PIL 兼容层的 Image 模块：PNG 8bit（灰度/RGB/RGBA，非隔行）的解码、几何与重采样。

对齐真实 PIL 的使用形状：`from PIL import Image` 得到的是**本模块**，
pdd.sh 用到的 `Image.open(...)` / `Image.LANCZOS` / `Image.new(...)` 都从模块取，
类本体是 Image.Image。只实现 pdd.sh 沙箱路径用到的那一小撮；行为按 Pillow
文档语义。任何不认识的东西抛 ValueError/NotImplementedError，不静默降级。
"""
import math
import struct
import zlib
from operator import mul

_builtin_open = open   # 模块级 open 稍后会被同名函数占掉，先把内建的存下来

# ---- 重采样常量（对齐 Pillow 的 Image.* 与 Image.Resampling.* 两套写法） ----
NEAREST = 0
LANCZOS = 1
BILINEAR = 2
BICUBIC = 3


class _Resampling:
    NEAREST = 0
    LANCZOS = 1
    BILINEAR = 2
    BICUBIC = 3


Resampling = _Resampling

_SIG = b"\x89PNG\r\n\x1a\n"
_CTYPE_BPP = {0: 1, 2: 3, 6: 4}
_CTYPE_MODE = {0: "L", 2: "RGB", 6: "RGBA"}
_MODE_CTYPE = {"L": 0, "RGB": 2, "RGBA": 6}
_MAX_PIXELS = 64 * 1024 * 1024   # 解压炸弹防线：超过直接拒绝
_MAX_DIM = 65535


def _clamp255(v):
    v = int(v + 0.5)
    return 0 if v < 0 else (255 if v > 255 else v)


# ---------------------------------------------------------------------------
# PNG 解码
# ---------------------------------------------------------------------------

def _decode_png(data):
    """-> (w, h, colortype, rows)；rows 是逐像素打包的字节行。"""
    if data[:8] != _SIG:
        raise ValueError("不是 PNG（签名不对）")
    pos = 8
    ihdr = None
    idat = bytearray()
    while pos + 8 <= len(data):
        (ln,) = struct.unpack_from(">I", data, pos)
        ctype = bytes(data[pos + 4:pos + 8])
        body = data[pos + 8:pos + 8 + ln]
        if len(body) != ln:
            raise ValueError("PNG 块在 %s 处截断" % ctype)
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos += 12 + ln
    if ihdr is None:
        raise ValueError("PNG 缺 IHDR")
    w, h, depth, color, comp, filt, interlace = ihdr
    if depth != 8:
        raise ValueError("只支持 8bit PNG：depth=%d" % depth)
    if color not in _CTYPE_BPP:
        raise ValueError("只支持灰度/RGB/RGBA PNG：colortype=%d" % color)
    if comp != 0 or filt != 0:
        raise ValueError("PNG 压缩/滤波方式不认识：comp=%d filt=%d" % (comp, filt))
    if interlace != 0:
        raise ValueError("不支持隔行 PNG")
    if not (0 < w <= _MAX_DIM and 0 < h <= _MAX_DIM) or w * h > _MAX_PIXELS:
        raise ValueError("PNG 尺寸不合法：%dx%d" % (w, h))
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        raise ValueError("PNG 像素数据解不开：%s" % e)
    bpp = _CTYPE_BPP[color]
    stride = w * bpp
    if len(raw) != (stride + 1) * h:
        raise ValueError("PNG 像素数据长度不对")
    rows = []
    prev = bytearray(stride)
    off = 0
    for _ in range(h):
        f = raw[off]
        off += 1
        row = bytearray(raw[off:off + stride])
        off += stride
        if f == 1:                                   # Sub
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif f == 2:                                 # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif f == 3:                                 # Average
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:                                 # Paeth
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa = p - a if p >= a else a - p
                pb = p - b if p >= b else b - p
                pc = p - c if p >= c else c - p
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                row[i] = (row[i] + pr) & 0xFF
        elif f != 0:
            raise ValueError("PNG 行滤波类型 %d 不认识" % f)
        rows.append(row)
        prev = row
    return w, h, color, rows


# ---------------------------------------------------------------------------
# PNG 编码（filter 0，zlib 压缩；与解码同一套块结构）
# ---------------------------------------------------------------------------

def _encode_png(mode, w, h, rows):
    ctype = _MODE_CTYPE[mode]
    bpp = _CTYPE_BPP[ctype]
    stride = w * bpp
    raw = bytearray()
    for row in rows:
        raw.append(0)
        raw += row[:stride]

    def chunk(t, b):
        return (struct.pack(">I", len(b)) + t + b
                + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF))

    out = bytearray(_SIG)
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    out += chunk(b"IEND", b"")
    return bytes(out)


# ---------------------------------------------------------------------------
# 重采样核
# ---------------------------------------------------------------------------

def _sinc(x):
    if x == 0.0:
        return 1.0
    px = math.pi * x
    return math.sin(px) / px


def _kern(radius, x):
    ax = -x if x < 0 else x
    if ax >= radius:
        return 0.0
    if radius == 1.0:                     # Bilinear
        return 1.0 - ax
    if radius == 2.0:                     # Bicubic
        if ax < 1.0:
            return 1.5 * ax * ax * ax - 2.5 * ax * ax + 1.0
        return -0.5 * ax * ax * ax + 2.5 * ax * ax - 4.0 * ax + 2.0
    return _sinc(x) * _sinc(x / radius)   # LANCZOS（radius=3）


def _axis_weights(in_n, out_n, radius):
    """每个输出下标 -> (lo, hi, 权重元组, 是否触边)。权重归一化，源下标按边界钳制。"""
    scale = in_n / out_n
    support = radius * (scale if scale > 1.0 else 1.0)
    div = scale if scale > 1.0 else 1.0
    ws = []
    for i in range(out_n):
        center = (i + 0.5) * scale - 0.5
        lo = int(math.ceil(center - support))
        hi = int(math.floor(center + support))
        ks = []
        total = 0.0
        clamped = False
        for j in range(lo, hi + 1):
            jj = 0 if j < 0 else (in_n - 1 if j >= in_n else j)
            if jj != j:
                clamped = True
            k = _kern(radius, (j - center) / div)
            ks.append(k)
            total += k
        if total == 0.0:
            total = 1.0
        ws.append((lo, hi, tuple(k / total for k in ks), clamped))
    return ws


# ---------------------------------------------------------------------------
# Image 类
# ---------------------------------------------------------------------------

class Image:
    """PNG 位图。惰性解码：open() 只解析头（只看 .size 的调用零像素成本）。"""

    def __init__(self, mode, size, rows, raw=None):
        self._mode = mode
        self._size = size
        self._rows = rows          # None = 还没解码，等 _raw
        self._raw = raw

    @property
    def mode(self):
        return self._mode

    @property
    def size(self):
        return self._size

    @property
    def width(self):
        return self._size[0]

    @property
    def height(self):
        return self._size[1]

    @property
    def im(self):
        raise NotImplementedError("兼容层不暴露内部 im 对象")

    def _px(self):
        if self._rows is None:
            w, h, color, rows = _decode_png(self._raw)
            self._rows = rows
            self._mode = _CTYPE_MODE[color]
            self._size = (w, h)
            self._raw = None
        return self._rows

    def _bpp(self):
        return _CTYPE_BPP[_MODE_CTYPE[self._mode]]

    # ---- 几何与像素操作 ----

    def crop(self, box):
        rows = self._px()
        w, h = self._size
        x0, y0, x1, y1 = [int(v) for v in box]
        x0 = max(0, min(w, x0)); x1 = max(0, min(w, x1))
        y0 = max(0, min(h, y0)); y1 = max(0, min(h, y1))
        if x1 <= x0 or y1 <= y0:
            raise ValueError("crop 出来是空图：%r" % (box,))
        bpp = self._bpp()
        rows2 = [bytearray(row[x0 * bpp:x1 * bpp]) for row in rows[y0:y1]]
        return Image(self._mode, (x1 - x0, y1 - y0), rows2)

    def convert(self, mode):
        rows = self._px()
        if mode == self._mode:
            return self
        if self._mode == "RGB" and mode == "L":
            out = []
            for row in rows:
                lr = bytearray(len(row) // 3)
                for i in range(0, len(row), 3):
                    lr[i // 3] = (row[i] * 299 + row[i + 1] * 587 + row[i + 2] * 114) // 1000
                out.append(lr)
            return Image("L", self._size, out)
        if self._mode == "RGBA" and mode == "RGB":
            out = []
            for row in rows:
                rgb = bytearray(len(row) // 4 * 3)
                for i in range(0, len(row), 4):
                    j = i // 4 * 3
                    rgb[j] = row[i]; rgb[j + 1] = row[i + 1]; rgb[j + 2] = row[i + 2]
                out.append(rgb)
            return Image("RGB", self._size, out)
        if self._mode == "L" and mode == "RGB":
            out = []
            for row in rows:
                rgb = bytearray(len(row) * 3)
                for i, v in enumerate(row):
                    rgb[i * 3] = v; rgb[i * 3 + 1] = v; rgb[i * 3 + 2] = v
                out.append(rgb)
            return Image("RGB", self._size, out)
        raise NotImplementedError("convert(%s -> %s) 不支持" % (self._mode, mode))

    def point(self, func):
        rows = self._px()
        if self._mode != "L":
            raise NotImplementedError("point() 只支持 L 模式")
        lut = [func(i) & 0xFF for i in range(256)]
        out = [bytes(lut[v] for v in row) for row in rows]
        return Image("L", self._size, out)

    def histogram(self):
        rows = self._px()
        bpp = self._bpp()
        hist = [0] * (256 * bpp)
        for row in rows:
            for v in row:
                hist[v] += 1
        return hist

    def resize(self, size, resample=NEAREST):
        rows = self._px()
        nw, nh = int(size[0]), int(size[1])
        if nw <= 0 or nh <= 0:
            raise ValueError("resize 目标尺寸不合法：%r" % (size,))
        if resample == LANCZOS:
            radius = 3.0
        elif resample == BICUBIC:
            radius = 2.0
        elif resample == BILINEAR:
            radius = 1.0
        elif resample == NEAREST:
            return self._resample_nearest(nw, nh)
        else:
            raise NotImplementedError("不认识的重采样方式：%r" % (resample,))
        w, h = self._size
        bpp = self._bpp()
        # 转通道平面（行内切片是 C 速度）；横、纵各跑一遍核卷积，纵向靠转置
        # 复用同一个循环，最后交织回行。转置用 zip(*rows)，C 速度。
        planes = [[row[c::bpp] for row in rows] for c in range(bpp)]
        planes = [self._resample_axis(p, w, nw, radius) for p in planes]
        planes = [[bytes(col) for col in zip(*p)] for p in planes]
        planes = [self._resample_axis(p, h, nh, radius) for p in planes]
        planes = [[bytes(col) for col in zip(*p)] for p in planes]
        out = []
        for r in range(nh):
            out.append(bytearray(
                v for t in zip(*(p[r] for p in planes)) for v in t))
        return Image(self._mode, (nw, nh), out)

    def save(self, path):
        rows = self._px()
        data = _encode_png(self._mode, self._size[0], self._size[1], rows)
        with _builtin_open(path, "wb") as f:
            f.write(data)

    # ---- 内部实现 ----

    def _resample_nearest(self, nw, nh):
        w, h = self._size
        bpp = self._bpp()
        rows = self._px()
        xmap = [min(w - 1, int((i + 0.5) * w / nw)) * bpp for i in range(nw)]
        out = []
        for j in range(nh):
            src = rows[min(h - 1, int((j + 0.5) * h / nh))]
            out.append(bytearray(b"".join(bytes(src[o:o + bpp]) for o in xmap)))
        return Image(self._mode, (nw, nh), out)

    @staticmethod
    def _resample_axis(rows, in_n, out_n, radius):
        """对「每行=一个采样序列」的平面图沿行方向重采样。

        横向直接用（采样轴就是行的主轴）；纵向在 resize() 里已把平面转成
        「每行=一列」，所以两个方向共用这套循环。权重每个输出下标只算一次、
        所有行复用；权重归一化后是凸组合，结果必在 0..255，只防浮点毛刺。
        """
        ws = _axis_weights(in_n, out_n, radius)
        out = []
        for row in rows:
            orow = bytearray(out_n)
            for i, (lo, hi, wlist, clamped) in enumerate(ws):
                if clamped:
                    acc = 0.0
                    for k, j in enumerate(range(lo, hi + 1)):
                        jj = 0 if j < 0 else (in_n - 1 if j >= in_n else j)
                        acc += row[jj] * wlist[k]
                else:
                    acc = sum(map(mul, row[lo:hi + 1], wlist))
                v = int(acc + 0.5)
                orow[i] = 255 if v > 255 else v
            out.append(orow)
        return out


# ---------------------------------------------------------------------------
# 模块级函数（真实 PIL 里 Image.open / Image.new 就是模块函数）
# ---------------------------------------------------------------------------

def open(path):
    """解析 PNG 头并返回惰性 Image；坏文件当场抛错（具体原因在像素访问时给全）。"""
    with _builtin_open(path, "rb") as f:
        data = f.read()
    if data[:8] != _SIG:
        raise ValueError("不是 PNG（签名不对）：%s" % path)
    if len(data) < 33:
        raise ValueError("PNG 太短：%s" % path)
    w, h, depth, color, comp, filt, interlace = struct.unpack_from(">IIBBBBB", data, 16)
    if depth != 8 or color not in _CTYPE_BPP or comp != 0 or filt != 0 or interlace != 0:
        # 头就不认识：让像素访问时由 _decode_png 抛具体错误，这里只给占位尺寸
        return Image("RGB", (0, 0), None, raw=data)
    return Image(_CTYPE_MODE[color], (w, h), None, raw=data)


def new(mode, size, color=0):
    """造一张纯色图（老 sbx.sh 的 Image.new 用法；本沙箱的 shot.png 生成也走这里）。"""
    w, h = int(size[0]), int(size[1])
    if mode == "L":
        v = color if isinstance(color, int) else int(color[0])
        row = bytearray([v & 0xFF]) * w
        rows = [bytearray(row) for _ in range(h)]
    elif mode == "RGB":
        r, g, b = (color + (0, 0))[:3] if isinstance(color, tuple) else (color, color, color)
        row = bytearray(bytes((r & 0xFF, g & 0xFF, b & 0xFF)) * w)
        rows = [bytearray(row) for _ in range(h)]
    else:
        raise NotImplementedError("new() 只支持 L/RGB")
    return Image(mode, (w, h), rows)
