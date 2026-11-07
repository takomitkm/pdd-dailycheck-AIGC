"""T16：调用计数证据自测——共享/惰性只减不需调用、语义集合不变。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import callcount  # noqa: E402


def test_shared_never_more_than_legacy():
    ts = ["popup", "subsidy", "bag", "light", "done", "exchange", "browse", "pend", "prize"]
    assert callcount.shared_calls(ts) <= callcount.legacy_calls(ts)


def test_shared_dedupes_channels_across_targets():
    # bag/light 都用 band+pill：共享后 band/pill 只算一次
    legacy = callcount.legacy_calls(["bag", "light"])
    shared = callcount.shared_calls(["bag", "light"])
    assert shared < legacy
    # 具体：legacy = 2*(1+1+3+4)=18；shared = 1+1+3+4=9
    assert legacy == 18 and shared == 9


def test_xml_resolves_skip_ocr():
    ts = ["popup", "subsidy", "bag"]
    assert callcount.lazy_calls(ts, {"popup", "subsidy", "bag"}) == 0
    assert callcount.lazy_calls(ts, set()) == callcount.shared_calls(ts)


def test_source_sets_unchanged_semantically():
    # 策略不改变「每个目标可用来源集合」——直接断言表未被改写
    assert callcount.TARGET_SOURCES["bag"] == ["xml", "psm11", "psm6", "band", "pill"]
    assert callcount.CHANNEL_CALLS["xml"] == 0


def test_main_report(tmp_path):
    out = tmp_path / "cc.json"
    assert callcount.main(["--frames", "10", "--out", str(out)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["kind"] == "t16-callcount"
    assert d["totals"]["shared"] == d["per_frame"]["shared"] * 10
    assert 0 < d["reduction_lazy_pct"] <= 100
