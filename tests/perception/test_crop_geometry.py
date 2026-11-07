"""T16/T18a：裁片通道几何——band/pill 的缩放与偏移必须进观察，否则坐标全错位。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pddcheck.domain import CoordinateSource, LocateStatus
from pddcheck.perception import (
    TargetLocateSpec,
    locate_all,
    observe_frame,
)
from pddcheck.vision.source import DeviceVisionSource

ROOT = Path(__file__).resolve().parents[2]
TSV_PILL = "5\t1\t1\t1\t1\t1\t130\t68\t38\t40\t92\t抽\n" \
           "5\t1\t1\t1\t1\t2\t183\t69\t27\t39\t37\t福\n" \
           "5\t1\t1\t1\t1\t3\t228\t68\t24\t38\t51\t袋\n"


class FakeEngine:
    def __init__(self, tsv=TSV_PILL):
        self.tsv = tsv
        self.calls = []

    def recognize(self, image, psm):
        from pddcheck.domain import ReadStatus
        from pddcheck.vision.tesseract import TsvResult
        self.calls.append(psm)
        return TsvResult(ReadStatus.OK, self.tsv, None, 0, "", 0.0, "x")


class FakeDevice:
    tap_width = 720
    tap_height = 1280
    state_epoch = 1

    def screenshot_bytes(self):
        return _png(720, 1280)

    def read_hierarchy(self):
        return "<hierarchy></hierarchy>"


def _png(w, h):
    """造一张最小合法 PNG（纯 stdlib，不依赖 compat/真 PIL 的 save 签名）。"""
    import struct
    import zlib
    raw = b""
    for _ in range(h):
        raw += b"\x00" + bytes([200, 180, 160] * w)
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _stub_prepare(src_obj, data, source):
    """替换真预处理（Windows 主 venv 无 PIL）：几何按整图与缩放算，与生产公式一致。"""
    from pddcheck.perception.geometry_map import scale_5dp
    iw, ih = 720, 1280
    if source is CoordinateSource.PILL:
        box = (339, 480, 200, 80)          # pill_crop_box(0.472,0.375,0.75,0.4375)
        div = src_obj.pill_div
    else:
        box = (0, 428, 720, 679)
        div = src_obj.band_scale
    sx = scale_5dp(src_obj.device.tap_width, iw * div)
    sy = scale_5dp(src_obj.device.tap_height, ih * div)
    ox = float(f"{box[0] / iw * src_obj.device.tap_width:.1f}")
    oy = float(f"{box[1] / ih * src_obj.device.tap_height:.1f}")
    return b"png", (sx, sy, ox, oy)


def test_pill_channel_registers_geometry_and_maps_to_point_space(monkeypatch):
    """pill 裁片：scale=720/(720*2)=0.5、offset=裁片原点回推；点必须在点空间。"""
    box = (0.472, 0.375, 0.75, 0.4375)
    src = DeviceVisionSource(FakeDevice(), FakeEngine(), pill_box=box,
                             pill_div=2, pill_mode="color")
    monkeypatch.setattr(src, "_prepare_crop", lambda data, source: _stub_prepare(src, data, source))
    obs = observe_frame(src, frame_id="f", capture_id="c", state_epoch=1,
                        tap_width=720, tap_height=1280,
                        channels=(CoordinateSource.PILL,))
    assert CoordinateSource.PILL in obs.geometries
    sx, sy, ox, oy = obs.geometries[CoordinateSource.PILL]
    assert sx == 0.5 and sy == 0.5            # 720/(720*2)
    assert ox == 339.0 and oy == 480.0

    results = locate_all(obs, {"bag": TargetLocateSpec(key="bag", labels=("抽福袋",),
                                                       min_overlap=3)}, min_conf=40)
    r = results["bag"]
    assert r.status is LocateStatus.MATCH
    # 词框并集 (130..252, 68..108) → 中心 (191, 88) → 191*0.5+339=434.5→434；88*0.5+480=524
    assert r.winning.tap_point[0] in (434, 435)
    assert r.winning.tap_point[1] == 524


def test_page_channel_geometry_is_identity():
    src = DeviceVisionSource(FakeDevice(), FakeEngine("5\t1\t1\t1\t1\t1\t100\t880\t100\t40\t92\t抽福袋\n"))
    obs = observe_frame(src, frame_id="f", capture_id="c", state_epoch=1,
                        tap_width=720, tap_height=1280,
                        channels=(CoordinateSource.TESSERACT_PAGE,))
    assert obs.geometries[CoordinateSource.TESSERACT_PAGE] == (1.0, 1.0, 0.0, 0.0)


def test_missing_pill_box_yields_no_text_and_no_geometry():
    src = DeviceVisionSource(FakeDevice(), FakeEngine(), pill_box=None)
    obs = observe_frame(src, frame_id="f", capture_id="c", state_epoch=1,
                        tap_width=720, tap_height=1280,
                        channels=(CoordinateSource.PILL,))
    assert CoordinateSource.PILL not in obs.ocr_texts
    assert CoordinateSource.PILL not in obs.geometries
