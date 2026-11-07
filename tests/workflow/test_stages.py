"""T11/T22：流程段测试——就绪/入口/福袋的决策与失败码（纯 Fake 页面序列，无设备）。"""

from __future__ import annotations

import pytest

from pddcheck.perception import TargetLocateSpec
from pddcheck.workflow.stages import (
    PageView,
    StageFailure,
    StagePolicy,
    StageRunner,
)

PKG = "com.xunmeng.pinduoduo"
HOME = "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
ACT = "com.xunmeng.pinduoduo.activity.NewPageActivity"

POLICY = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=2, prove_max=3)

SUBSIDY = TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3)
BAG = TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3,
                       coord=(0.13889, 0.69922))


class Actor:
    def __init__(self):
        self.calls = []

    def __call__(self, kind, point):
        self.calls.append((kind, point))
        return None


def runner(pages, actor=None):
    """pages: 观察序列（每次 read_page 弹一个），末尾重复最后一个。"""
    seq = list(pages)

    def read():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    act = actor or Actor()
    return StageRunner(read, act, POLICY), act


def test_ensure_ready_starts_app_when_not_foreground():
    r, act = runner([PageView("com.android.launcher3", "Launcher", ""),
                     PageView(PKG, HOME, "")])
    r.ensure_ready()
    kinds = [c[0] for c in act.calls]
    assert kinds == ["wake", "dismiss_keyguard", "start"]


def test_ensure_ready_noop_when_already_in_pdd():
    r, act = runner([PageView(PKG, ACT, "")])
    r.ensure_ready()
    assert act.calls == []


def test_ensure_ready_rc7_when_launch_fails():
    r, act = runner([PageView("com.android.launcher3", "Launcher", "")])
    with pytest.raises(StageFailure) as e:
        r.ensure_ready()
    assert e.value.rc == 7


def test_enter_subsidy_taps_and_stops_when_in_activity():
    r, act = runner([PageView(PKG, HOME, "百亿补贴 搜索补贴"),
                     PageView(PKG, ACT, "")])
    r.enter_subsidy(SUBSIDY)
    assert [c[0] for c in act.calls] == ["tap"]


def test_enter_subsidy_retries_with_back_then_fails_rc4():
    # 每次都在首页，且 tap 后焦点仍在首页 → 用完 entry_retry → rc4
    r, act = runner([PageView(PKG, HOME, "百亿补贴")])
    with pytest.raises(StageFailure) as e:
        r.enter_subsidy(SUBSIDY)
    assert e.value.rc == 4
    kinds = [c[0] for c in act.calls]
    assert kinds.count("back") == POLICY.entry_retry      # 退两次


def test_open_bag_proves_by_progress_count():
    r, act = runner([PageView(PKG, ACT, "抽福袋"),
                     PageView(PKG, ACT, "9天内点亮4次必得")])
    r.open_bag(BAG)
    assert [c[0] for c in act.calls] == ["tap"]


def test_open_bag_proves_by_pend_text():
    r, act = runner([PageView(PKG, ACT, "抽福袋"),
                     PageView(PKG, ACT, "点亮任务已完成 3天后可兑换")])
    r.open_bag(BAG)
    assert [c[0] for c in act.calls] == ["tap"]


def test_open_bag_backs_to_next_carousel_frame_then_proves():
    r, act = runner([PageView(PKG, ACT, "抽福袋"),        # 第 1 帧：点了但没证明
                     PageView(PKG, ACT, "抽福袋"),        # back 后换帧
                     PageView(PKG, ACT, "9天内点亮4次必得")])  # 第 2 帧：证明成功
    r.open_bag(BAG)
    kinds = [c[0] for c in act.calls]
    assert kinds == ["tap", "back", "tap"]


def test_open_bag_fails_rc5_when_never_proves():
    r, act = runner([PageView(PKG, ACT, "抽福袋")])
    with pytest.raises(StageFailure) as e:
        r.open_bag(BAG)
    assert e.value.rc == 5
    assert [c[0] for c in act.calls].count("back") == POLICY.prove_max - 1
