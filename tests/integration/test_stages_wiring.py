"""T31：stages 串进 bootstrap——默认关闭（行为不变）、开启后按序执行并可失败收手。"""

from __future__ import annotations

import pytest

from pddcheck.cli.bootstrap import PipelineConfig, build_and_run
from pddcheck.device import FakeDevice
from pddcheck.domain import ExecutionStatus, ReadStatus
from pddcheck.notify import NotificationSender
from pddcheck.perception import TargetLocateSpec
from pddcheck.storage import DailyStore, Journal
from pddcheck.vision.tesseract import TsvResult

PKG = "com.xunmeng.pinduoduo"
HOME = "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
ACT = "com.xunmeng.pinduoduo.activity.NewPageActivity"

ROW_ENTRY = "5\t1\t1\t1\t1\t1\t100\t600\t200\t40\t92\t百亿补贴\n"
ROW_BAG = "5\t1\t2\t1\t2\t1\t435\t524\t100\t40\t92\t抽福袋\n"
ROW_ACT = ("5\t1\t3\t1\t3\t1\t100\t200\t400\t40\t90\t9天内再点亮5次必得\n"
           "5\t1\t4\t1\t4\t1\t100\t290\t200\t40\t92\t今日已点亮\n")


class ScriptedDevice(FakeDevice):
    def __init__(self, *a, navigate=True, **k):
        super().__init__(*a, **k)
        self.activity = HOME
        self.navigate = navigate

    def read_hierarchy(self):
        return "<hierarchy></hierarchy>"

    def screenshot_bytes(self):
        return b"\x89PNG"

    def execute(self, intent, point=None):
        from pddcheck.domain import ActionReceipt
        # 模拟真实跳转：start → 首页；tap → 活动页；back → 首页
        if self.navigate:
            if intent.kind.value == "start":
                self.activity = HOME
            elif intent.kind.value == "tap":
                self.activity = ACT
            elif intent.kind.value == "back":
                self.activity = HOME
        self.executed.append(intent)
        return ActionReceipt(intent.action_id, ExecutionStatus.ACKNOWLEDGED, 1, 1)


class StagedEngine:
    """按当前 activity 返回不同文本。"""

    def __init__(self, device):
        self.device = device

    def info(self):
        return None

    def recognize(self, image, psm):
        act = self.device.activity
        tsv = ROW_ACT if act == ACT else (ROW_ENTRY + ROW_BAG)
        return TsvResult(ReadStatus.OK, tsv, None, 0, "", 0.0, "x")


def _cfg(tmp_path, **kw):
    base = dict(business_date="2026-11-07", run_id="r", evidence_dir=str(tmp_path / "ev"),
                endpoint=None,
                specs={"subsidy": TargetLocateSpec(key="subsidy", labels=("百亿补贴",),
                                                   min_overlap=3, coord=(0.125, 0.46875)),
                       "bag": TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3),
                       "light": TargetLocateSpec(key="light", labels=("立即点亮",),
                                                 min_overlap=4)})
    base.update(kw)
    return PipelineConfig(**base)


def _deps(tmp_path, cfg, *, navigate=True):
    dev = ScriptedDevice(now_ns=lambda: 1000, tap_size=(720, 1280), navigate=navigate)
    return dict(device=dev, engine=StagedEngine(dev),
                store=DailyStore(tmp_path / "runs", tmp_path / "pause"),
                notifier=NotificationSender(transport=lambda u, t: (200, '{"code":0}')),
                journal=Journal(tmp_path / "j.jsonl"), cfg=cfg, now_ns=lambda: 1000)


def test_stages_off_by_default(tmp_path):
    out, stats = build_and_run(**_deps(tmp_path, _cfg(tmp_path)))
    assert stats["stages"] == []                  # 默认不跑流程段
    assert stats["observe_calls"] >= 1


def test_stages_on_runs_ready_entry_bag_then_facts(tmp_path, monkeypatch):
    import pddcheck.vision.source as src_mod
    monkeypatch.setattr(src_mod.DeviceVisionSource, "_prepare_crop",
                        lambda self, data, source: (b"png", (1.0, 1.0, 0.0, 0.0)))
    cfg = _cfg(tmp_path, run_stages=True, step_wait_s=0)
    out, stats = build_and_run(**_deps(tmp_path, cfg))
    assert stats["stages"][:3] == ["ready:ok", "entry:ok", "bag:ok"], stats
    # 进活动页后读到 done → lit1
    assert out.lit == 1 and out.marker_written


def test_stage_failure_maps_to_rc_and_no_marker(tmp_path, monkeypatch):
    """入口进不去 → rc4，不写标记。"""
    import pddcheck.vision.source as src_mod
    monkeypatch.setattr(src_mod.DeviceVisionSource, "_prepare_crop",
                        lambda self, data, source: (b"png", (1.0, 1.0, 0.0, 0.0)))
    cfg = _cfg(tmp_path, run_stages=True, step_wait_s=0, entry_retry=0)
    d = _deps(tmp_path, cfg, navigate=False)   # 点了也不跳转 → 入口必失败
    # 设备永远停在首页、文本无「百亿补贴」→ 入口必失败
    d["device"].activity = HOME
    d["engine"] = type("E", (), {
        "info": lambda self: None,
        "recognize": lambda self, image, psm: TsvResult(
            ReadStatus.OK, "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t92\t推荐\n", None, 0, "", 0.0, "x"),
    })()
    out, stats = build_and_run(**d)
    assert any(s.startswith("failed:rc4") for s in stats["stages"]), stats
    assert out.rc == 4 and not out.marker_written
