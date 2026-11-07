"""步骤判定核（T11 2/2）——do_step 内四个决策点的纯函数化（pdd.sh:1069-1134）。

每个函数回答「下一步做什么/是否收手」，设备动作由执行器执行。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StepAction(StrEnum):
    PROCEED = "proceed"                # 照常点这一枪
    SCROLL_TOP_FIRST = "scroll_top"    # 入口没认到字：先滑到顶再认一轮（每步至多一次）
    REFUSE_COORD = "refuse_coord"      # 核实/恢复路上只认出坐标：拒绝盲点（I05）
    RETRY_WITH_BACK = "retry_back"     # 入口被吃：BACK 退掉再点一次
    STUCK_RC4 = "stuck_rc4"            # 入口连着吃枪：收手 rc4，不进 bag 扫描


def top_retry_decision(*, key: str, top_retry_key: str, find_method: str,
                       scrolled_once: bool) -> StepAction:
    """入口只认字：认不到多半是页面没在顶端——滑回最顶端再认一轮（旧 L1074-1078）。"""
    if key == top_retry_key and find_method == "coord" and not scrolled_once:
        return StepAction.SCROLL_TOP_FIRST
    return StepAction.PROCEED


def recovery_coord_decision(*, in_recovery: bool, find_method: str,
                            recovery_no_coord: bool) -> StepAction:
    """核实/恢复这一路只认字：分数=0 的坐标兜底是 10-11 的盲点（I05，旧 L1082-1085）。"""
    if in_recovery and recovery_no_coord and find_method == "coord":
        return StepAction.REFUSE_COORD
    return StepAction.PROCEED


def entry_guard_decision(*, key: str, top_retry_key: str, now_activity: str,
                         home_activities: tuple[str, ...], entered_count: int,
                         entry_retry: int) -> StepAction:
    """点完还在首页 = 这一枪被遮罩吃了（旧 L1092-1104）。

    - 判据是「前台还是不是首页」（子串匹配，与旧 is_home_page 一致——同名 Activity
      ≠ 同页的残留风险记在 B08）；
    - 只对入口键生效；最多退 entry_retry 次，持续失败 rc4，绝不掉进 bag 扫描（I07）。
    """
    if key != top_retry_key:
        return StepAction.PROCEED
    is_home = any(ha in now_activity for ha in home_activities if ha) if now_activity else False
    if not is_home:
        return StepAction.PROCEED
    if entered_count < entry_retry:
        return StepAction.RETRY_WITH_BACK
    return StepAction.STUCK_RC4


@dataclass(frozen=True, slots=True)
class ProofOutcome:
    ok: bool
    reason: str          # count / pend / done_fallback / carousel_wrong_frame
    after_count: int | None = None


def proof_ok_decision(*, count: int | None, pend_text: str | None,
                      done_text: str | None) -> ProofOutcome:
    """轮播位点进活动页的唯一凭据是进度行（旧 proof_ok L1202-1225）。

    顺序不能乱：count → pend → done 兜底；三个都没有 = 停在轮播另一帧，BACK 重试。
    """
    if count is not None:
        return ProofOutcome(True, "count", count)
    if pend_text is not None:
        return ProofOutcome(True, "pend")
    if done_text is not None:
        return ProofOutcome(True, "done_fallback")
    return ProofOutcome(False, "carousel_wrong_frame")


def back_on_page_decision(*, key: str, top_retry_key: str, page_act: str | None,
                          now_activity: str | None) -> bool:
    """BACK 把人退出活动页了就重走一遍入口（旧 back_on_page L1060-1067）。"""
    if key == top_retry_key:
        return False
    if not page_act:
        return False
    return now_activity != page_act
