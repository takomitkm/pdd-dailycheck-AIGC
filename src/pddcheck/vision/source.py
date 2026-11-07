"""设备+引擎 → ObservationSource 适配（组合根用）。

DeviceVisionSource 把 ObservationPort/DevicePort 与 OcrEngine 接成 observe_frame
需要的取数接口：fetch_xml = 设备层级；fetch_ocr = 取当前帧像素 → 引擎识别 → TSV。
一帧只取一次像素（帧缓存），避免每通道重复截图。
"""

from __future__ import annotations

from pddcheck.domain import CoordinateSource
from pddcheck.vision.engine import OcrEngine


class DeviceVisionSource:
    def __init__(self, device, engine: OcrEngine, *, psm: int = 6,
                 screenshot=None) -> None:
        self.device = device
        self.engine = engine
        self.psm = psm
        # screenshot: () -> bytes|None；默认用设备的 screenshot_bytes（若有）
        self._screenshot = screenshot or getattr(device, "screenshot_bytes", None)
        self._frame: bytes | None = None
        self._frame_taken = False

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
        res = self.engine.recognize(data, self.psm)
        from pddcheck.domain import ReadStatus
        return res.tsv_text if res.status is ReadStatus.OK else None

    def reset(self) -> None:
        """换帧时调用：清帧缓存，下一次取数重新截图。"""
        self._frame = None
        self._frame_taken = False
