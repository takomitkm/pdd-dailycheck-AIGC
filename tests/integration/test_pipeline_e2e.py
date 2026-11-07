"""T14/T20：组合根端到端——真实类装配（FakeDevice + 假引擎）走完点亮全链路。"""

from __future__ import annotations

from pddcheck.cli.bootstrap import PipelineConfig, build_and_run
from pddcheck.device import FakeDevice
from pddcheck.domain import ReadStatus
from pddcheck.notify import NotificationSender
from pddcheck.perception import TargetLocateSpec
from pddcheck.storage import DailyStore, Journal
from pddcheck.vision.engine import EngineInfo
from pddcheck.vision.tesseract import TsvResult

ROW_BAG = "5\t1\t1\t1\t1\t1\t100\t880\t100\t40\t92\t抽福袋"
ROW_LIGHT = "5\t1\t2\t1\t2\t1\t100\t1000\t120\t40\t91\t立即点亮"
ROW_COUNT_BEFORE = "5\t1\t3\t1\t3\t1\t100\t200\t400\t40\t90\t9天内点亮4次必得"
ROW_COUNT_AFTER = "5\t1\t3\t1\t3\t1\t100\t200\t400\t40\t90\t9天内点亮3次必得"
ROW_DONE = "5\t1\t4\t1\t4\t1\t100\t1000\t200\t40\t92\t今日已点亮"


class PipelineDevice(FakeDevice):
    def read_hierarchy(self):
        return "<hierarchy></hierarchy>"

    def screenshot_bytes(self):
        return b"\x89PNG-fake"


class SeqEngine:
    def __init__(self, tsvs):
        self._tsvs = list(tsvs)
        self.calls = 0

    def info(self):
        return EngineInfo("fake-engine", "0", None)

    def recognize(self, image, psm):
        t = self._tsvs[min(self.calls, len(self._tsvs) - 1)]
        self.calls += 1
        return TsvResult(ReadStatus.OK, t, None, 0, "", 0.0, "0")


def _deps(tmp_path, *, tsvs):
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    cfg = PipelineConfig(
        business_date="2026-11-07", run_id="run-p", evidence_dir=str(tmp_path / "ev"),
        endpoint="http://stub/x", page_kind="activity",
        specs={"bag": TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3),
               "light": TargetLocateSpec(key="light", labels=("立即点亮",), min_overlap=4)})
    return dict(device=PipelineDevice(now_ns=lambda: 1000, tap_size=(720, 1280)),
                engine=SeqEngine(tsvs), store=store,
                notifier=NotificationSender(transport=lambda u, t: (200, '{"code":0}')),
                journal=Journal(tmp_path / "j.jsonl"), cfg=cfg, now_ns=lambda: 1000)


def test_pipeline_end_to_end_lit3(tmp_path):
    d = _deps(tmp_path, tsvs=["\n".join([ROW_BAG, ROW_LIGHT, ROW_COUNT_BEFORE]),
                              "\n".join([ROW_BAG, ROW_LIGHT, ROW_COUNT_AFTER])])
    out, stats = build_and_run(**d)
    assert out.lit == 3 and out.marker_written
    # 观察两次：点前事实 + 点后核实（共享观察一帧一取）
    assert stats["observe_calls"] == 2
    assert len(d["device"].executed) == 1


def test_pipeline_done_path_no_tap(tmp_path):
    d = _deps(tmp_path, tsvs=["\n".join([ROW_BAG, ROW_DONE])])
    out, stats = build_and_run(**d)
    assert out.lit == 1 and out.marker_written
    assert len(d["device"].executed) == 0      # done 不点
    assert stats["observe_calls"] == 1


def test_pipeline_pend_lit4(tmp_path):
    pend = "5\t1\t5\t1\t5\t1\t100\t300\t400\t40\t90\t点亮任务已完成3天后可兑换"
    d = _deps(tmp_path, tsvs=["\n".join([ROW_BAG, pend])])
    out, _ = build_and_run(**d)
    assert out.lit == 4 and out.ledger_written == 3
