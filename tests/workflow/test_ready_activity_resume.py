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

    def __call__(self, kind, point):
        self.calls.append((kind, point))
        return None


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


def test_on_stale_activity_page_clean_restarts_no_rc7():
    """11-10 定案（取代 11-09「可续跑」）：停在陈旧活动/店铺页 → force-stop 干净拉起；
    重启后只要焦点是 PDD 就不 rc7。"""
    r, act = runner([PageView(PKG, ACT, ACT_TEXT)])
    r.ensure_ready()
    assert [c[0] for c in act.calls] == ["stop", "wake", "dismiss_keyguard", "start"]


def test_clean_restart_lands_home():
    r, act = runner([PageView(PKG, ACT, CHANNEL_TEXT),
                     PageView(PKG, HOME, "推荐 食品 女装")])
    r.ensure_ready()
    assert [c[0] for c in act.calls] == ["stop", "wake", "dismiss_keyguard", "start"]


def test_rc7_only_when_focus_never_reaches_pdd():
    """rc7 只留给「焦点真的不是 PDD」；过夜锁屏轮询重发生命周期仍起不来才报。"""
    seq = [PageView("com.android.launcher3", "Launcher", "")] * 9
    act = Actor()
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
                      step_wait_s=0, sleep=lambda s: None)
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[-1],
                    lambda kind, point: act(kind, point), pol)
    with pytest.raises(StageFailure) as e:
        r.ensure_ready(launch_wait_s=0.01)
    assert e.value.rc == 7
    assert any(c[0] == "wake" for c in act.calls)


def test_pagekind_activity_still_classifies():
    from pddcheck.perception.pagekind import classify_page
    assert classify_page(ACT_TEXT) is PageKind.ACTIVITY
