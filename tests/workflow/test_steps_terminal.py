"""T11(2/2)：步骤判定核与终态收尾的真值表——期望对齐 47 场景与 acceptance §5。"""

from __future__ import annotations

from pddcheck.workflow import (
    CheckBeforeKind,
    ClosePolicy,
    StepAction,
    back_on_page_decision,
    check_done_before_decision,
    entry_guard_decision,
    proof_ok_decision,
    recovery_coord_decision,
    terminal_plan,
    top_retry_decision,
)

HOME_ACTS = ("com.xunmeng.pinduoduo.ui.activity.MainFrameActivity",
             "com.xunmeng.pinduoduo.ui.activity.HomeActivity")


# --------------------------------------------------------------- 步骤判定核


def test_top_retry_only_for_entry_key_coord_and_once():
    assert top_retry_decision(key="subsidy", top_retry_key="subsidy",
                              find_method="coord", scrolled_once=False
                              ) is StepAction.SCROLL_TOP_FIRST
    # 已经滑过一次：不再滑（topped=1，旧 L1074）
    assert top_retry_decision(key="subsidy", top_retry_key="subsidy",
                              find_method="coord", scrolled_once=True
                              ) is StepAction.PROCEED
    # bag 认不到走坐标：不触发滑顶（只对入口键）
    assert top_retry_decision(key="bag", top_retry_key="subsidy",
                              find_method="coord", scrolled_once=False
                              ) is StepAction.PROCEED


def test_recovery_coord_ban_case30():
    assert recovery_coord_decision(in_recovery=True, find_method="coord",
                                   recovery_no_coord=True) is StepAction.REFUSE_COORD
    # 主线第一枪坐标兜底照旧（I04）
    assert recovery_coord_decision(in_recovery=False, find_method="coord",
                                   recovery_no_coord=True) is StepAction.PROCEED


def test_entry_guard_retry_then_stuck_case12_case13():
    common = dict(key="subsidy", top_retry_key="subsidy",
                  now_activity="com.xunmeng.pinduoduo.ui.activity.HomeActivity",
                  home_activities=HOME_ACTS, entry_retry=2)
    assert entry_guard_decision(entered_count=0, **common) is StepAction.RETRY_WITH_BACK
    assert entry_guard_decision(entered_count=1, **common) is StepAction.RETRY_WITH_BACK
    assert entry_guard_decision(entered_count=2, **common) is StepAction.STUCK_RC4
    # 点完进了活动页：不触发
    left = dict(common, now_activity="com.xunmeng.pinduoduo.activity.NewPageActivity")
    assert entry_guard_decision(entered_count=0, **left) is StepAction.PROCEED


def test_entry_guard_never_applies_to_bag():
    assert entry_guard_decision(key="bag", top_retry_key="subsidy",
                                now_activity="com.xunmeng.pinduoduo.ui.activity.HomeActivity",
                                home_activities=HOME_ACTS, entered_count=0,
                                entry_retry=2) is StepAction.PROCEED


def test_proof_ok_order_count_pend_done():
    assert proof_ok_decision(count=3, pend_text="待兑换",
                             done_text="已使用").reason == "count"
    assert proof_ok_decision(count=None, pend_text="待兑换",
                             done_text="已使用").reason == "pend"
    assert proof_ok_decision(count=None, pend_text=None,
                             done_text="已使用").reason == "done_fallback"
    miss = proof_ok_decision(count=None, pend_text=None, done_text=None)
    assert not miss.ok and miss.reason == "carousel_wrong_frame"   # case37


def test_back_on_page_rules():
    # 入口键自己永远不触发（返回 False）；PAGE_ACT 未记录不触发；前台变了才触发
    assert not back_on_page_decision(key="subsidy", top_retry_key="subsidy",
                                     page_act="NewPageActivity", now_activity="HomeActivity")
    assert not back_on_page_decision(key="bag", top_retry_key="subsidy",
                                     page_act=None, now_activity="HomeActivity")
    assert back_on_page_decision(key="bag", top_retry_key="subsidy",
                                 page_act="NewPageActivity", now_activity="HomeActivity")


# --------------------------------------------------------------- 终态收尾


def test_terminal_lit3_case11():
    p = terminal_plan(rc=0, lit=3, ledger_current=3)
    assert p.marker_write and p.ledger_write == 0          # case39：账 3 清 0
    assert p.close_policy is ClosePolicy.STOP_AND_HOME
    assert p.notify_title == "PDD ✅" and p.final_scroll


def test_terminal_lit1_used_title_case28():
    p = terminal_plan(rc=0, lit=1, done_word="5折 最高减15元 已使用")
    assert p.marker_write and p.ledger_write == 0
    assert p.notify_title == "PDD 已使用"                   # used-title-split 变异钉的字节


def test_terminal_lit1_plain_title_case09():
    p = terminal_plan(rc=0, lit=1, done_word="今日已点亮")
    assert p.notify_title == "PDD ✅"


def test_terminal_lit2_stays_case10():
    p = terminal_plan(rc=0, lit=2, ledger_current=1)
    assert not p.marker_write and p.ledger_write == 0       # 倒数作废
    assert p.close_policy is ClosePolicy.STAY and not p.final_scroll
    assert p.notify_title == "PDD 需人工"


def test_terminal_lit4_pend_days_copy_and_roll():
    p = terminal_plan(rc=0, lit=4, pend_days=3)              # case26：屏幕 3 照抄（账 9 也照抄）
    assert p.marker_write and p.ledger_write == 3 and p.close_policy is ClosePolicy.STAY
    p = terminal_plan(rc=0, lit=4, pend_days=None, ledger_current=3)   # case25：账 3 减 1
    assert p.ledger_write == 2
    p = terminal_plan(rc=0, lit=4, pend_days=None, ledger_current=None)  # case23：一个字不写
    assert p.ledger_write is None
    p = terminal_plan(rc=0, lit=4, pend_days=1)              # case24：照抄 1 不写 0
    assert p.ledger_write == 1
    assert p.notify_title == "PDD 💡"


def test_terminal_rc6_case34():
    p = terminal_plan(rc=6, lit=None)
    assert not p.marker_write and p.ledger_write is None
    assert p.close_policy is ClosePolicy.HOME_ONLY and not p.final_scroll   # B07：只有 HOME
    assert p.notify_title == "PDD ⬛ 退出码 6"


def test_terminal_rc4_rc5_titles():
    assert terminal_plan(rc=4, lit=None).notify_title == "PDD ❌ 退出码 4"
    assert terminal_plan(rc=5, lit=None).notify_title == "PDD ❌ 退出码 5"


def test_terminal_rc0_lit0_compat_branch_b05():
    # B05：rc0&lit0 旧代码会滑+写标记——静态不可达，但兼容保留且显式标注
    p = terminal_plan(rc=0, lit=0)
    assert p.marker_write and p.final_scroll and p.ledger_write == 0
