"""设备+引擎 → ObservationSource（组合根用）。

- 一帧只截一次像素（帧缓存），所有通道复用同一帧；
- 整页通道直接喂引擎；band/pill 通道先按标定框裁片+预处理，再喂引擎，
  并把该通道的几何（缩放/偏移）登记给 observe_frame——裁片坐标必须换算回点空间。
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

from pddcheck.domain import CoordinateSource, ReadStatus
from pddcheck.vision.engine import OcrEngine


class DeviceVisionSource:
    def __init__(self, device, engine: OcrEngine, *, psm: int = 6,
                 screenshot=None, band_region=None, pill_box=None,
                 band_scale: int = 3, band_cutoff: int = 1,
                 pill_div: int = 2, pill_th: int = 120, pill_mode: str = "color") -> None:
        self.device = device
        self.engine = engine
        self.psm = psm
        self._screenshot = screenshot or getattr(device, "screenshot_bytes", None)
        self._frame: bytes | None = None
        self._frame_taken = False
        self.band_region = band_region
        self.pill_box = pill_box
        self.band_scale = band_scale
        self.band_cutoff = band_cutoff
        self.pill_div = pill_div
        self.pill_th = pill_th
        self.pill_mode = pill_mode
        self._geometry: dict[CoordinateSource, tuple[float, float, float, float]] = {}

    # ---- 取数 -------------------------------------------------------
    def _pixels(self) -> bytes | None:
        if not self._frame_taken:
            self._frame = self._screenshot() if self._screenshot else None
            self._frame_taken = True
        return self._frame

    def fetch_xml(self):
        try:
            return self.device.read_hierarchy()
        except Exception:
            return None

    def fetch_ocr(self, source: CoordinateSource):
        data = self._pixels()
        if data is None:
            return None
        if source is CoordinateSource.TESSERACT_PAGE:
            res = self.engine.recognize(data, self.psm)
            if res.status is ReadStatus.OK:
                self._geometry[source] = (1.0, 1.0, 0.0, 0.0)
                return res.tsv_text
            return None
        # band / pill：裁片 + 预处理（坐标必须带几何回推）
        prepared, geom = self._prepare_crop(data, source)
        if prepared is None:
            return None
        tmp = _write_temp(prepared)
        try:
            res = self.engine.recognize(tmp, 7 if source is CoordinateSource.PILL else self.psm)
        finally:
            tmp.unlink(missing_ok=True)
        if res.status is not ReadStatus.OK:
            return None
        self._geometry[source] = geom
        return res.tsv_text

    def _prepare_crop(self, png: bytes, source: CoordinateSource):
        """返回 (预处理后 PNG bytes, (scale_x, scale_y, ox, oy))；几何按整图与缩放算。"""
        try:
            from PIL import Image
            from pddcheck.vision.preprocess import (
                band_crop_box, pill_crop_box, preprocess_band, preprocess_pill,
            )
            from pddcheck.perception.geometry_map import scale_5dp
        except Exception:
            return None, None
        im = Image.open(io.BytesIO(png))
        iw, ih = im.width, im.height
        if iw <= 0 or ih <= 0:
            return None, None
        if source is CoordinateSource.BAND:
            if self.band_region is None:
                return None, None
            box = band_crop_box(self.band_region, iw, ih)
            if box[2] <= 8 or box[3] <= 8:
                return None, None
            img = preprocess_band(im, box, scale=self.band_scale, cutoff=self.band_cutoff)
            div = self.band_scale
        else:
            if self.pill_box is None:
                return None, None
            box = pill_crop_box(self.pill_box, iw, ih)
            if box[2] <= 8 or box[3] <= 8:
                return None, None
            img = preprocess_pill(im, box, div=self.pill_div, th=self.pill_th,
                                  mode=self.pill_mode)
            div = self.pill_div
        buf = io.BytesIO()
        try:
            img.save(buf, format="PNG")
        except TypeError:                      # compat PIL 的 save 不接 format
            img.save(buf)
        tap_w, tap_h = getattr(self.device, "tap_width", 0) or iw, \
            getattr(self.device, "tap_height", 0) or ih
        # 旧脚本同款：scale = TAP_W / 整图宽 / 放大倍数（5 位小数）；offset = 裁片原点回推（1 位）
        sx = scale_5dp(tap_w, iw * div) if div > 1 else scale_5dp(tap_w, iw)
        sy = scale_5dp(tap_h, ih * div) if div > 1 else scale_5dp(tap_h, ih)
        ox = float(f"{box[0] / iw * tap_w:.1f}")
        oy = float(f"{box[1] / ih * tap_h:.1f}")
        return buf.getvalue(), (sx, sy, ox, oy)

    def geometry_for(self, source: CoordinateSource):
        return self._geometry.get(source)

    def reset(self) -> None:
        """换帧时调用：清帧缓存与几何。"""
        self._frame = None
        self._frame_taken = False
        self._geometry.clear()


def _write_temp(data: bytes) -> Path:
    fh = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fh.write(data)
    fh.close()
    return Path(fh.name)
