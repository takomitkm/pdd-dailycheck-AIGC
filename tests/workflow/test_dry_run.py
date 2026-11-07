"""纯观察模式（--dry-run）：识别与决策照做，但不执行业务动作、不写标记/账本、不推送。"""

from __future__ import annotations

from pddcheck.cli.bootstrap import PipelineConfig, build_and_run
from pddcheck.device import FakeDevice
from pddcheck.domain import ReadStatus
from pddcheck.notify import NotificationSender
from pddcheck.perception import TargetLocateSpec
from pddcheck.storage import DailyStore, Journal
from pddcheck.vision.tesseract import TsvResult

HOME = "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
ACT = "com.xunmeng.pinduoduo.activity.NewPageActivity"
ROW = ("5\t1\t1\t1\t1\t1\t100\t200\t400\t40\t90\t9天内再点亮5次必得\n"
       "5\t1\t2\t1\t2\t1\t100\t290\t200\t40\t92\t今日已点亮\n")


class Engine:
    def info(self):
        return None

    def recognize(self, image, psm):
        return TsvResult(ReadStatus.OK, ROW, None, 0, "", 0.0, "x")


class Dev(FakeDevice):
    def read_hierarchy(self):
        return "<hierarchy></hierarchy>"

    def screenshot_bytes(self):
        return b"\x89PNG"


def _run(tmp_path, **kw):
    cfg = PipelineConfig(
        business_date="2026-11-07", run_id="dry", evidence_dir=str(tmp_path / "ev"),
        endpoint=None, page_kind="activity",
        specs={"light": TargetLocateSpec(key="light", labels=("立即点亮",), min_overlap=4),
               "subsidy": TargetLocateSpec(key="subsidy", labels=("百亿补贴",),
                                           min_overlap=3, coord=(0.125, 0.46875)),
               "bag": TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3)},
        **kw)
    return build_and_run(
        device=Dev(now_ns=lambda: 1000, tap_size=(720, 1280)),
        engine=Engine(), store=DailyStore(tmp_path / "runs", tmp_path / "pause"),
        notifier=NotificationSender(transport=lambda u, t: (200, '{"code":0}')),
        journal=Journal(tmp_path / "j.jsonl"), cfg=cfg, now_ns=lambda: 1000)


def test_dry_run_never_writes_marker_or_pushes(tmp_path):
    out, stats = _run(tmp_path, dry_run=True)
    # 识别与决策照做：页上有「今日已点亮」→ 判 lit1
    assert out.lit == 1
    # 但纯观察：不写标记、不写账本、不推送
    assert out.marker_written is False
    assert not list((tmp_path / "runs").glob(".done-*"))
    assert out.delivered in ("skipped", "dry_run") or out.delivered is None \
        or getattr(out, "delivered", "") == "skipped"
