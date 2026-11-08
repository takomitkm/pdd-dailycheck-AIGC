"""生产补签（11-08）教训：手机停在点亮活动页时 ensure_ready 不得 rc7——活动页可直接续跑。"""

from __future__ import annotations

import pytest

from pddcheck.perception.pagekind import PageKind
from pddcheck.workflow.stages import (
    PageView, StageFailure, StagePolicy, StageRunner,
)

PKG = "com.xunmeng.pinduoduo"
HOME = "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
ACT = "com.xunmeng.pinduoduo.activity.NewPageActivity"

ACT_TEXT = "9天内再点亮5次必得 共100元券 今日已点亮"
CHANNEL_TEXT = "百亿补贴品质保障 抢低至5折 频道专享"


class Actor:
    def __init__(self):
        self.calls = []


def runner(pages, policy=None):
    seq = list(pages)
    act = Actor()

    def _act(kind, point):
        act.calls.append((kind, point))
        return None

    return StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[-1], _act,
                       policy or StagePolicy(pkg=PKG, home_activity=HOME,
                                             entry_retry=0, prove_max=1,
                                             step_wait_s=0)), act


def test_on_activity_page_directly_returns_without_back():
    """生产教训：停在活动页（非 HomeActivity）→ 直接续跑，不 BACK、不 rc7。"""
    r, act = runner([PageView(PKG, ACT, ACT_TEXT)])
    r.ensure_ready()
    assert act.calls == []


def test_back_landing_on_activity_page_also_accepts():
    """BACK 途中落到活动页也算可用起点。"""
    r, act = runner([PageView(PKG, ACT, CHANNEL_TEXT),
                     PageView(PKG, ACT, ACT_TEXT)])
    r.ensure_ready()
    assert [c[0] for c in act.calls] == ["back"]


def test_still_fails_rc7_when_nowhere_usable():
    r, act = runner([PageView(PKG, ACT, CHANNEL_TEXT)])
    with pytest.raises(StageFailure) as e:
        r.ensure_ready()
    assert e.value.rc == 7


def test_pagekind_activity_still_classifies():
    from pddcheck.perception.pagekind import classify_page
    assert classify_page(ACT_TEXT) is PageKind.ACTIVITY
