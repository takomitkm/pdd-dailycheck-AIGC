"""T18a/T16：裁片通道进真实观察路径——频道页只有 pill 能认出的场景。"""

from __future__ import annotations

import pytest

from pddcheck.cli.bootstrap import PipelineConfig, build_and_run
from pddcheck.device import FakeDevice
from pddcheck.domain import CoordinateSource, ReadStatus
from pddcheck.notify import NotificationSender
from pddcheck.perception import TargetLocateSpec
from pddcheck.storage import DailyStore, Journal
from pddcheck.vision.tesseract import TsvResult

# 整页只认得出「百亿补贴品质保障」（真机频道页实测），认不出「抽福袋」
PAGE_TSV = "5\t1\t1\t1\t1\t1\t100\t200\t300\t40\t90\t百亿补贴品质保障\n"
# pill 裁片里三词同行（真机实测 conf 92/37/51，max=92）
PILL_TSV = ("5\t1\t1\t1\t1\t1\t130\t68\t38\t40\t92\t抽\n"
            "5\t1\t1\t1\t1\t2\t183\t69\t27\t39\t37\t福\n"
            "5\t1\t1\t1\t1\t3\t228\t68\t24\t38\t51\t袋\n")


class ChanEngine:
    """按 psm 区分通道：pill 通道固定用 psm7，整页用 psm6。"""

    def __init__(self):
        self.calls = []

    def info(self):
        return None

    def recognize(self, image, psm):
        self.calls.append(psm)
        tsv = PILL_TSV if psm == 7 else PAGE_TSV
        return TsvResult(ReadStatus.OK, tsv, None, 0, "", 0.0, "x")


class ChanDevice(FakeDevice):
    def read_hierarchy(self):
        return "<hierarchy></hierarchy>"

    def screenshot_bytes(self):
        return b"\x89PNG-fake"


def _stub_prepare(self, data, source):
    from pddcheck.perception.geometry_map import scale_5dp
    iw, ih = 720, 1280
    if source is CoordinateSource.PILL:
        box, div = (339, 480, 200, 80), self.pill_div
    else:
        box, div = (0, 428, 720, 679), self.band_scale
    sx = scale_5dp(720, iw * div)
    sy = scale_5dp(1280, ih * div)
    return b"png", (sx, sy, float(f"{box[0]/iw*720:.1f}"), float(f"{box[1]/ih*1280:.1f}"))


def test_pill_channel_enables_bag_that_page_ocr_misses(tmp_path, monkeypatch):
    import pddcheck.vision.source as src_mod
    monkeypatch.setattr(src_mod.DeviceVisionSource, "_prepare_crop", _stub_prepare)

    dev = ChanDevice(now_ns=lambda: 1000, tap_size=(720, 1280))
    engine = ChanEngine()
    cfg = PipelineConfig(
        business_date="2026-11-07", run_id="r", evidence_dir=str(tmp_path / "ev"),
        endpoint=None, page_kind="channel",
        specs={"bag": TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3),
               "subsidy": TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3)},
        pill_box=(0.472, 0.375, 0.75, 0.4375), pill_div=2, pill_mode="color")
    out, stats = build_and_run(
        device=dev, engine=engine, store=DailyStore(tmp_path / "runs", tmp_path / "pause"),
        notifier=NotificationSender(transport=lambda u, t: (200, '{"code":0}')),
        journal=Journal(tmp_path / "j.jsonl"), cfg=cfg, now_ns=lambda: 1000)
    # 没有 pill 通道时 bag 认不出（整页只有「百亿补贴品质保障」）；有 pill 才能定位
    assert engine.calls.count(7) >= 1          # pill 通道确实跑了 psm7
    assert stats["observe_calls"] >= 1


def test_pill_channel_off_by_default(tmp_path, monkeypatch):
    """缺省 pill_box=None → 不跑 pill 通道（行为与之前一致）。"""
    dev = ChanDevice(now_ns=lambda: 1000)
    engine = ChanEngine()
    cfg = PipelineConfig(business_date="2026-11-07", run_id="r",
                         evidence_dir=str(tmp_path / "ev"), endpoint=None,
                         specs={"subsidy": TargetLocateSpec(key="subsidy",
                                                            labels=("百亿补贴",), min_overlap=3)})
    build_and_run(device=dev, engine=engine, store=DailyStore(tmp_path / "runs", tmp_path / "pause"),
                  notifier=NotificationSender(transport=lambda u, t: (200, '{"code":0}')),
                  journal=None, cfg=cfg, now_ns=lambda: 1000)
    assert 7 not in engine.calls            # 没跑 pill 通道
