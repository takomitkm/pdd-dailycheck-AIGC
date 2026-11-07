"""T07.4/T16：引擎适配器测试——两后端产出同一 TSV 形状、独占、失败分型、跨引擎一致。"""

from __future__ import annotations

import pytest

from pddcheck.domain import ReadStatus
from pddcheck.perception import parse_tsv
from pddcheck.vision.engine import (
    EngineLease,
    RapidOcrEngine,
    TesseractEngine,
    detections_to_tsv,
)
from pddcheck.vision.tesseract import TesseractConfig


class FakeCompleted:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def box(l, t, r, b):
    return [[l, t], [r, t], [r, b], [l, b]]


# --------------------------------------------------------------- RapidOCR 形状


def test_detections_to_tsv_is_parseable_by_same_parser():
    dets = [
        (box(100, 880, 200, 920), "抽福袋", 0.92),
        (box(100, 1000, 220, 1040), "立即点亮", 0.88),
    ]
    lines = parse_tsv(detections_to_tsv(dets))
    assert [ln.normalized_text for ln in lines] == ["抽福袋", "立即点亮"]
    assert lines[0].max_conf == 92          # 0.92 → 92
    assert (lines[0].left, lines[0].top, lines[0].right, lines[0].bottom) == (100, 880, 200, 920)


def test_detections_trim_tabs_and_skip_empty():
    dets = [(box(0, 0, 10, 10), "a\tb\nc", 0.9),
            (box(0, 0, 10, 10), "   ", 0.9)]
    lines = parse_tsv(detections_to_tsv(dets))
    assert len(lines) == 1 and lines[0].normalized_text == "abc"


def test_rapid_engine_ok_and_invalid():
    class Good:
        def __call__(self, path):
            return ([([[0, 0], [10, 0], [10, 10], [0, 10]], "抽福袋", 0.9)], None)
    eng = RapidOcrEngine(engine=Good(), version="1.4.4")
    res = eng.recognize("/tmp/x.png", 6)
    assert res.status is ReadStatus.OK and "抽福袋" in res.tsv_text
    assert eng.info().engine_id == "rapidocr-onnx"

    class Boom:
        def __call__(self, path):
            raise RuntimeError("model missing")
    res2 = RapidOcrEngine(engine=Boom()).recognize("/tmp/x.png", 6)
    assert res2.status is ReadStatus.INVALID and res2.error_code == "rapid_RuntimeError"


# --------------------------------------------------------------- Tesseract 包装


def test_tesseract_engine_maps_through():
    def fake_runner(argv, timeout):
        return FakeCompleted(0, "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t92\t抽福袋\n", "")
    eng = TesseractEngine(TesseractConfig(), version="tesseract 5.5.0", runner=fake_runner)
    res = eng.recognize("/tmp/x.png", 6)
    assert res.status is ReadStatus.OK and res.engine_version == "tesseract 5.5.0"
    assert eng.info().engine_id == "tesseract-cli"


# --------------------------------------------------------------- 独占


def test_engine_lease_exclusive():
    eng = RapidOcrEngine(engine=object(), version="x")
    with EngineLease(eng):
        with pytest.raises(RuntimeError, match="独占"):
            EngineLease(eng)
    with EngineLease(eng):      # 释放后可再拿
        pass


# --------------------------------------------------------------- 跨引擎一致


def test_cross_engine_same_shape_and_geometry():
    dets = [(box(100, 880, 200, 920), "抽福袋", 0.92)]
    rapid_tsv = detections_to_tsv(dets)
    tess_tsv = "5\t1\t1\t1\t1\t1\t100\t880\t100\t40\t92\t抽福袋\n"
    a = parse_tsv(rapid_tsv)[0]
    b = parse_tsv(tess_tsv)[0]
    assert a.normalized_text == b.normalized_text
    assert (a.left, a.top, a.right, a.bottom) == (b.left, b.top, b.right, b.bottom)
    assert a.max_conf == b.max_conf
