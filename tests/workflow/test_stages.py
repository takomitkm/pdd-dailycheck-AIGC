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

POLICY = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=2, prove_max=3,
                     step_wait_s=0)          # 测试不真睡

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
    # G6（迁移审计）：焦点读得到且是别的应用 → 先 force-stop 再拉起（旧脚本 RESTART_APP）
    assert kinds == ["stop", "wake", "dismiss_keyguard", "start"]


def test_ensure_ready_clean_restarts_when_focus_unreadable():
    """11-10 定案：不在首页就 force-stop 干净拉起（RESTART_APP），焦点读不到也重启
    （force-stop 对陈旧页是 intended；冷启动组件名已修，能可靠回首页）。"""
    seq = [PageView(None, None, ""), PageView(PKG, HOME, "")]
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=2, prove_max=3,
                      step_wait_s=0, focus_retry=1, sleep=lambda s: None)
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    r.ensure_ready()
    kinds = [c[0] for c in r._act.calls]
    assert kinds == ["stop", "wake", "dismiss_keyguard", "start"]


def test_ensure_ready_retries_unreadable_focus_then_proceeds():
    """G7（迁移审计）：焦点读不到先重试几次再判定（旧脚本 FOCUS_RETRY，
    躲过渡动画那一瞬）。第二轮读到了外国应用 → 正常走 stop→wake→…。"""
    seq = [PageView(None, None, ""), PageView("com.android.launcher3", "Launcher", ""),
           PageView(PKG, HOME, "")]
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=2, prove_max=3,
                      step_wait_s=0, sleep=lambda s: None)
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    r.ensure_ready()
    kinds = [c[0] for c in r._act.calls]
    assert kinds == ["stop", "wake", "dismiss_keyguard", "start"]


def test_ensure_ready_restarts_stale_pdd_page_to_home():
    """11-10：在 PDD 但停在陈旧店铺/促销页（非首页）→ force-stop 干净拉起到首页，
    不再「续跑错页」（那会让 entry 假 ok → bag rc5）。"""
    r, act = runner([PageView(PKG, ACT, "消费券页"),
                     PageView(PKG, HOME, "")])
    r.ensure_ready()
    assert [c[0] for c in act.calls] == ["stop", "wake", "dismiss_keyguard", "start"]


def test_ensure_ready_in_pdd_nonhome_never_rc7_after_clean_restart():
    """干净重启后只要焦点是 PDD 就不报 rc7（哪怕落在活动页而非首页）。"""
    r, act = runner([PageView(PKG, ACT, "消费券页")])
    r.ensure_ready()
    kinds = [c[0] for c in act.calls]
    assert kinds[0] == "stop"
    assert "start" in kinds


def test_ensure_ready_noop_when_already_in_pdd():
    r, act = runner([PageView(PKG, HOME, "")])
    r.ensure_ready()
    assert act.calls == []


def test_ensure_ready_rc7_when_launch_fails():
    r, act = runner([PageView("com.android.launcher3", "Launcher", "")])
    with pytest.raises(StageFailure) as e:
        r.ensure_ready()
    assert e.value.rc == 7


def test_enter_subsidy_taps_and_stops_when_in_activity():
    r, act = runner([PageView(PKG, HOME, "百亿补贴 搜索补贴"),
                     PageView(PKG, ACT, "抽福袋 精选 奢品馆")])
    r.enter_subsidy(SUBSIDY)
    assert [c[0] for c in act.calls] == ["tap"]


def test_enter_subsidy_retries_with_back_then_fails_rc4():
    """每一枪点错就 BACK 退掉（pdd.sh 同款），用完 entry_retry+1 枪 → rc4。"""
    r, act = runner([PageView(PKG, HOME, "百亿补贴")])
    with pytest.raises(StageFailure) as e:
        r.enter_subsidy(SUBSIDY)
    assert e.value.rc == 4
    kinds = [c[0] for c in act.calls]
    # entry_retry+1 枪，每枪点错退一次
    assert kinds.count("tap") == POLICY.entry_retry + 1
    assert kinds.count("back") == POLICY.entry_retry + 1


def test_enter_subsidy_uses_coord_fallback_when_text_not_found():
    """认不到字、又没有锚点供给器时用标定坐标点一次（旧脚本同款：入口是艺术字图片）。"""
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1, step_wait_s=0)
    seq = [PageView(PKG, HOME, "限时秒杀 免费领礼物"), PageView(PKG, ACT, "抽福袋")]
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    spec = TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3,
                            coord=(0.125, 0.46875))
    r.enter_subsidy(spec)
    # 坐标换算：0.125*720=90、0.46875*1280=600
    assert r._act.calls == [("tap", (90, 600))]


def test_enter_subsidy_anchor_point_used_when_text_not_found():
    """11-13 加固：认不到字时先用**锚点推算**的点（优先于固定坐标）。"""
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1, step_wait_s=0)
    seq = [PageView(PKG, HOME, "限时秒杀 免费领礼物"), PageView(PKG, ACT, "抽福袋")]
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    spec = TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3,
                            coord=(0.125, 0.46875))
    r.enter_subsidy(spec, anchor_points=lambda: [(36, 772)])
    assert r._act.calls == [("tap", (36, 772))]      # 锚点点，没用坐标


def test_enter_subsidy_anchor_wrong_point_backs_and_tries_next():
    """锚点候选点错了 → BACK 退掉再试下一个（点错就退，不拿盲点冒充成功）。"""
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1, step_wait_s=0)
    seq = [PageView(PKG, HOME, "限时秒杀"),
           PageView(PKG, HOME, "限时秒杀"),      # 第一个候选点错（还在首页）
           PageView(PKG, ACT, "抽福袋 精选 奢品馆")]   # 第二个候选点对
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    spec = TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3,
                            coord=(0.125, 0.46875))
    r.enter_subsidy(spec, anchor_points=lambda: [(36, 700), (36, 772)])
    assert r._act.calls == [("tap", (36, 700)), ("back", None), ("tap", (36, 772))]


def test_enter_subsidy_empty_anchors_falls_back_to_coord():
    """锚点认不到（空列表）→ 落到标定坐标（不是不点）。"""
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1, step_wait_s=0)
    seq = [PageView(PKG, HOME, "限时秒杀"), PageView(PKG, ACT, "抽福袋")]
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    spec = TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3,
                            coord=(0.125, 0.46875))
    r.enter_subsidy(spec, anchor_points=lambda: [])
    assert r._act.calls == [("tap", (90, 600))]


def test_enter_subsidy_empty_anchor_list_does_not_blind_tap():
    """锚点供给器给不出候选（认不到锚点）且**也没有坐标** → 不点这一枪（绝不盲点）。"""
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1, step_wait_s=0)
    seq = [PageView(PKG, HOME, "限时秒杀")]
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    spec = TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3,
                            coord=None, allow_coord=False)
    with pytest.raises(StageFailure) as e:
        r.enter_subsidy(spec, anchor_points=lambda: [])
    assert e.value.rc == 4
    assert [c[0] for c in r._act.calls] == []        # 一个 tap 都没有


def test_enter_subsidy_waits_step_after_tap():
    """真机实测：点击后必须等跳转，否则判「没进去」。"""
    slept = []
    pol = StagePolicy(pkg=PKG, home_activity=HOME, entry_retry=0, prove_max=1,
                      step_wait_s=4.0, sleep=lambda s: slept.append(s))
    seq = [PageView(PKG, HOME, "限时秒杀"), PageView(PKG, ACT, "抽福袋")]
    r = StageRunner(lambda: seq.pop(0) if len(seq) > 1 else seq[0], Actor(), pol)
    spec = TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3,
                            coord=(0.125, 0.46875))
    r.enter_subsidy(spec)
    assert slept == [4.0]


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


def test_open_bag_retries_tap_without_blind_back_then_proves():
    """点完证明不了时不再盲目 BACK（真机踩过：BACK 会把已进的活动页退回频道页）。
    只重新观察/再点，直到证明成功。"""
    r, act = runner([PageView(PKG, ACT, "抽福袋"),        # 第 1 帧：点了但没证明
                     PageView(PKG, ACT, "抽福袋"),        # 再观察一轮
                     PageView(PKG, ACT, "9天内点亮4次必得")])  # 证明成功
    r.open_bag(BAG)
    kinds = [c[0] for c in act.calls]
    assert "back" not in kinds                    # 绝不盲目 BACK
    assert kinds.count("tap") >= 1


def test_open_bag_fails_rc5_when_never_proves():
    r, act = runner([PageView(PKG, ACT, "抽福袋")])
    with pytest.raises(StageFailure) as e:
        r.open_bag(BAG)
    assert e.value.rc == 5
    # 点过但证明不了 → 用完 prove_max 次观察后失败，期间没有 BACK 死循环
    assert "back" not in [c[0] for c in act.calls]
