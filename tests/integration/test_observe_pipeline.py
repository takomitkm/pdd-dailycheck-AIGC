"""T16：共享观察驱动端到端——同一帧取数一次，locate_all 出点，run_once 完成点亮。

证明 -87% 的结构优化落到可运行管线上：9 目标共享 1 次 XML + N 次通道取数，
而不是每目标各取一遍。
"""

from __future__ import annotations

from pddcheck.domain import CoordinateSource, LocateStatus
from pddcheck.perception import (
    TargetLocateSpec,
    locate_all,
    observe_frame,
)
from tests.support.flowh import after, run_case

XML = "<hierarchy><node text='百亿补贴' content-desc='' resource-id='' bounds='[10,10][200,50]'/></hierarchy>"
TSV = ("5\t1\t1\t1\t1\t1\t100\t880\t100\t40\t92\t抽福袋\n"
       "5\t1\t2\t1\t2\t1\t100\t1000\t120\t40\t91\t立即点亮\n")


class Vision:
    def __init__(self):
        self.calls = 0

    def fetch_xml(self):
        self.calls += 1
        return XML

    def fetch_ocr(self, source):
        self.calls += 1
        return TSV


def test_shared_observation_feeds_flow_with_minimal_fetches(tmp_path):
    vision = Vision()
    obs = observe_frame(vision, frame_id="f1", capture_id="cap1", state_epoch=0,
                        tap_width=720, tap_height=1280,
                        channels=(CoordinateSource.TESSERACT_PAGE,))
    assert vision.calls == 2                       # 1 xml + 1 通道（与目标数无关）

    specs = {
        "subsidy": TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3),
        "bag": TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3,
                                coord=(0.13889, 0.69922)),
        "light": TargetLocateSpec(key="light", labels=("立即点亮",), min_overlap=4),
    }
    results = locate_all(obs, specs, min_conf=40)
    assert results["bag"].status is LocateStatus.MATCH
    assert results["light"].status is LocateStatus.MATCH

    # 用共享观察得出的点击点驱动 run_once（点前 4 次 → 点后 3 次 = 点亮成功）
    facts = {"before_count": 4, "tap_point": results["light"].winning.tap_point,
             "tap_method": "ocr"}
    out, dev, store = run_case(tmp_path, facts=facts, obs=after(3))
    assert out.lit == 3 and out.marker_written
    assert len(dev.executed) == 1
    assert vision.calls == 2                       # 整个流程只取了这批观察，不重复
