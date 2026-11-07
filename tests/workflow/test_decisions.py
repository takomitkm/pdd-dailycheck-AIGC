"""T11：判定核真值表——期望值全部来自 47 场景与 verify_light 源码逐行推演。"""

from __future__ import annotations

from pddcheck.workflow import (
    CheckBeforeKind,
    check_done_before_decision,
)
from pddcheck.workflow.verify import (
    ProofKind,
    VerifyObservation,
    VerifyStage,
    verify_light_decision,
)


def V(stage, after=None, done=False, prize=False, pend=False, fail=False):
    return VerifyObservation(stage, after_count=after, done_text=done,
                             prize_text=prize, pend_text=pend, reenter_failed=fail)


# --------------------------------------------------------------- 计数核实


def test_counter_decrease_is_the_primary_proof():
    out = verify_light_decision(4, "ocr", (V(VerifyStage.AFTER_DIRECT, after=3),))
    assert out.rc == 0 and out.lit == 3
    assert out.proof_kind is ProofKind.COUNTER_DECREASE


def test_counter_unchanged_is_rc6_case34():
    out = verify_light_decision(4, "ocr", (V(VerifyStage.AFTER_DIRECT, after=4),))
    assert out.rc == 1 and out.lit is None
    assert out.proof_kind is ProofKind.NONE
    assert "没变小" in out.why


def test_counter_up_also_fails():
    out = verify_light_decision(3, "ocr", (V(VerifyStage.AFTER_DIRECT, after=5),))
    assert out.rc == 1


# --------------------------------------------------------------- 文本救场阶梯


def test_done_text_after_direct_counts_as_done():
    out = verify_light_decision(4, "ocr", (V(VerifyStage.AFTER_DIRECT, done=True),))
    assert out.rc == 0 and out.lit == 3 and out.proof_kind is ProofKind.SCREEN_DONE


def test_prize_overlay_is_prize_proof_case19():
    out = verify_light_decision(4, "ocr", (V(VerifyStage.AFTER_POPUP, prize=True),))
    assert out.rc == 0 and out.lit == 3 and out.proof_kind is ProofKind.PRIZE


def test_pend_after_popup_maps_to_lit4_case22():
    out = verify_light_decision(None, "ocr", (V(VerifyStage.AFTER_POPUP, pend=True),))
    assert out.rc == 4 and out.lit == 4 and out.proof_kind is ProofKind.PENDING


def test_done_after_popup_clearing_counts():
    out = verify_light_decision(4, "ocr", (V(VerifyStage.AFTER_POPUP, done=True),))
    assert out.rc == 0 and out.proof_kind is ProofKind.SCREEN_DONE


def test_pend_before_done_in_priority_order():
    # 同一观察同时带 prize/pend/done：prize → pend → done 的顺序不能乱（旧 L1342-1357）
    out = verify_light_decision(None, "ocr", (V(VerifyStage.AFTER_POPUP, prize=True, pend=True, done=True),))
    assert out.proof_kind is ProofKind.PRIZE
    out = verify_light_decision(None, "ocr", (V(VerifyStage.AFTER_POPUP, pend=True, done=True),))
    assert out.proof_kind is ProofKind.PENDING


# --------------------------------------------------------------- browse 两落点


def test_back_direct_read_case16():
    out = verify_light_decision(4, "ocr", (V(VerifyStage.AFTER_BACK, after=3),))
    assert out.rc == 0 and out.proof_kind is ProofKind.COUNTER_DECREASE


def test_back_to_channel_then_reenter_case15():
    obs = (V(VerifyStage.AFTER_BACK, after=None),
           V(VerifyStage.AFTER_REENTER, after=3))
    out = verify_light_decision(4, "ocr", obs)
    assert out.rc == 0 and out.proof_kind is ProofKind.COUNTER_DECREASE


def test_reenter_route_failure_is_rc6_case35_path():
    obs = (V(VerifyStage.AFTER_BACK, after=None),
           V(VerifyStage.AFTER_REENTER, after=None),
           V(VerifyStage.AFTER_REENTER_BAG, after=None, fail=True))
    out = verify_light_decision(4, "ocr", obs)
    assert out.rc == 1 and "重进福袋页失败" in out.why


# --------------------------------------------------------------- 兜底两分支


def test_coord_gun_without_counter_cannot_pass_case35():
    obs = (V(VerifyStage.AFTER_DIRECT, after=None),)
    out = verify_light_decision(None, "coord", obs)
    assert out.rc == 1 and out.proof_kind is ProofKind.NONE
    assert "无法核实" in out.why


def test_text_gun_without_counter_is_legacy_weak_proof_b04():
    obs = (V(VerifyStage.AFTER_DIRECT, after=None),)
    out = verify_light_decision(None, "ocr", obs)
    assert out.rc == 0 and out.lit == 3
    assert out.proof_kind is ProofKind.LEGACY_TEXT_WITHOUT_COUNTER


def test_before_missing_and_after_present_cannot_compare_weak_proof():
    # before 读不到（None）：数字对比不成立 → 走兜底分支（文字枪=弱证明）
    out = verify_light_decision(None, "ocr", (V(VerifyStage.AFTER_DIRECT, after=3),))
    assert out.rc == 0 and out.proof_kind is ProofKind.LEGACY_TEXT_WITHOUT_COUNTER


# --------------------------------------------------------------- 点前终态


def test_check_before_priority_done_exchange_pend():
    assert check_done_before_decision(done_text="今日已点亮", exchange_text=None,
                                      pend_text=None, before_count=4).kind is CheckBeforeKind.DONE
    assert check_done_before_decision(done_text=None, exchange_text="立即兑换",
                                      pend_text="待兑换", before_count=4).kind is CheckBeforeKind.EXCHANGE
    assert check_done_before_decision(done_text=None, exchange_text=None,
                                      pend_text="点亮任务已完成 3天后可兑换",
                                      before_count=None).kind is CheckBeforeKind.PENDING


def test_check_before_proceed_carries_before_maybe_none():
    out = check_done_before_decision(done_text=None, exchange_text=None,
                                     pend_text=None, before_count=6)
    assert out.kind is CheckBeforeKind.PROCEED and out.before_count == 6
    out = check_done_before_decision(done_text=None, exchange_text=None,
                                     pend_text=None, before_count=None)
    assert out.kind is CheckBeforeKind.PROCEED and out.before_count is None


def test_check_before_done_carries_screen_word():
    out = check_done_before_decision(done_text="已使用", exchange_text=None,
                                     pend_text=None, before_count=4)
    assert out.done_word == "已使用" and out.lit == 1
