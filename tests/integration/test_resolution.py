"""T15/T16：47×2 —— 同一批流程场景在 1440×2560 点空间下结果不变（分辨率无关）。

决策核与退出映射不含分辨率依赖；坐标兜底在 1440×2560 下按 half-up 截断，
仍落在同一语义分支（MATCH / lit）。band/pill 的 5dp 缩放另见 perception 测试。
"""

from __future__ import annotations

import pytest

from pddcheck.exits import ExitCode
from tests.support.flowh import after, after_popup, run_case

TAP = (1440, 2560)
PAID = {"before_count": 4, "tap_point": (200, 1790)}

CASES = [
    ("done", dict(facts={"done_text": "今日已点亮"}, tap=TAP),
     dict(code=ExitCode.OK, lit=1, marker=True)),
    ("exchange", dict(facts={"exchange_text": "立即兑换", "before_count": 4}, tap=TAP),
     dict(code=ExitCode.OK, lit=2, marker=False)),
    ("lit3", dict(facts=PAID, obs=after(3), tap=TAP),
     dict(code=ExitCode.OK, lit=3, marker=True)),
    ("rc6", dict(facts=PAID, obs=after(4), tap=TAP),
     dict(code=ExitCode.LIGHT_NOT_APPLIED, lit=None, marker=False)),
    ("pend", dict(facts={"pend_text": "待兑换", "pend_days": 2}, tap=TAP),
     dict(code=ExitCode.OK, lit=4, ledger=2)),
    ("prize", dict(facts=PAID, obs=after_popup(prize_text=True), tap=TAP),
     dict(code=ExitCode.OK, lit=3, marker=True)),
]


@pytest.mark.parametrize("name,kwargs,exp", CASES, ids=[c[0] for c in CASES])
def test_resolution_1440x2560(name, kwargs, exp, tmp_path):
    out, dev, store = run_case(tmp_path / name, **kwargs)
    assert out.exit_code is exp["code"], f"{name}: {out.exit_code}"
    if "lit" in exp:
        assert out.lit == exp["lit"]
    if "marker" in exp:
        assert out.marker_written is exp["marker"]
    if "ledger" in exp:
        assert out.ledger_written == exp["ledger"]


def test_coord_fallback_scales_to_tap_space(tmp_path):
    # 720×1280: (0.13889*720+0.5, 0.69922*1280+0.5) → (100, 895)
    from pddcheck.perception import emit_point, scale_5dp
    sx = scale_5dp(1440, 720)   # 2.0
    sy = scale_5dp(2560, 1280)  # 2.0
    assert emit_point(100, 895, sx, sy) == (200, 1790)
