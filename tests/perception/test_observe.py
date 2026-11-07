"""T16：同帧共享观察——取数次数证明 + 与逐目标定位的语义等价。"""

from __future__ import annotations

import pytest

from pddcheck.domain import CoordinateSource, LocateStatus
from pddcheck.perception import (
    TargetLocateSpec,
    locate_all,
    observe_frame,
)
from pddcheck.perception.locate import ParsedFrame, locate_candidates
from pddcheck.perception.ocr_pass import OcrPassInput

XML = "<hierarchy><node text='百亿补贴' content-desc='' resource-id='' bounds='[10,10][100,40]'/></hierarchy>"
TSV = ("5\t1\t1\t1\t1\t1\t100\t880\t100\t40\t92\t抽福袋\n"
       "5\t1\t2\t1\t2\t1\t100\t1000\t100\t40\t90\t立即点亮\n")


class CountingSource:
    def __init__(self):
        self.calls = []
        self._xml = XML
        self._ocr = {CoordinateSource.TESSERACT_PAGE: TSV, CoordinateSource.BAND: TSV}

    def fetch_xml(self):
        self.calls.append("xml")
        return self._xml

    def fetch_ocr(self, source):
        self.calls.append(f"ocr:{source.value}")
        return self._ocr.get(source)


SPECS = {
    "subsidy": TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3),
    "bag": TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3,
                            coord=(0.13889, 0.69922)),
    "light": TargetLocateSpec(key="light", labels=("立即点亮",), min_overlap=4),
    "done": TargetLocateSpec(key="done", labels=("今日已点亮",), min_overlap=3,
                             allow_coord=False),
}


def test_observe_fetches_each_channel_once_not_per_target():
    src = CountingSource()
    obs = observe_frame(src, frame_id="f", capture_id="c", state_epoch=1,
                        tap_width=720, tap_height=1280,
                        channels=(CoordinateSource.TESSERACT_PAGE, CoordinateSource.BAND))
    # 4 个目标却只取 1(xml)+2(通道)=3 次——不是 4×(1+2)=12
    assert src.calls == ["xml", "ocr:tesseract_page", "ocr:band"]
    assert obs.fetch_calls == ("xml", "ocr:tesseract_page", "ocr:band")


def test_locate_all_uses_single_observation_and_matches_per_target():
    src = CountingSource()
    obs = observe_frame(src, frame_id="f", capture_id="c", state_epoch=1,
                        tap_width=720, tap_height=1280,
                        channels=(CoordinateSource.TESSERACT_PAGE, CoordinateSource.BAND))
    results = locate_all(obs, SPECS, min_conf=40)
    assert set(results) == set(SPECS)
    assert results["subsidy"].status is LocateStatus.MATCH
    assert results["bag"].status is LocateStatus.MATCH
    # 取数已在 observe_frame 完成，locate_all 不再增加调用
    assert len(src.calls) == 3

    # 语义等价：逐个用同一批文本构造 ParsedFrame 再定位，结果应与 locate_all 一致
    pf = ParsedFrame("f", "c", 1, 720, 1280, xml_text=XML,
                     ocr_passes=(OcrPassInput(source=CoordinateSource.TESSERACT_PAGE, tsv_text=TSV),
                                 OcrPassInput(source=CoordinateSource.BAND, tsv_text=TSV)))
    for key, spec in SPECS.items():
        single = locate_candidates(pf, spec, min_conf=40)
        assert single.status is results[key].status, key
        if single.winning and results[key].winning:
            assert single.winning.tap_point == results[key].winning.tap_point, key


def test_duplicate_channel_request_is_programming_error():
    src = CountingSource()
    with pytest.raises(ValueError, match="重复"):
        observe_frame(src, frame_id="f", capture_id="c", state_epoch=1,
                      tap_width=720, tap_height=1280,
                      channels=(CoordinateSource.BAND, CoordinateSource.BAND))


def test_nine_targets_still_only_five_fetches():
    """9 目标 × 5 源的老账 69 次 → 共享后固定 1+通道数。"""
    src = CountingSource()
    specs = {f"k{i}": TargetLocateSpec(key=f"k{i}", labels=("抽福袋",), min_overlap=3)
             for i in range(9)}
    obs = observe_frame(src, frame_id="f", capture_id="c", state_epoch=1,
                        tap_width=720, tap_height=1280,
                        channels=(CoordinateSource.TESSERACT_PAGE, CoordinateSource.BAND))
    locate_all(obs, specs, min_conf=40)
    assert len(src.calls) == 3                      # 9 个目标仍是 3 次取数
