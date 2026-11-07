"""终态收尾计划（T11 2/2）——cmd_run 收尾段（L1589-1674）的纯函数化。

对应 acceptance §5 的效果映射表：lit/rc → 标记/账本/关应用/推送标题。
注意三点（都是已定案口径，不是可选项）：
- lit=2/4 之后一个按键都不多放、不关 app（I02/I13）；
- rc≠0 的收尾只有 HOME（没有 force-stop）——B07；
- rc∈{2,3,69,78,73,75} 是收尾段之前的早退：零设备动作、rc2/3 有对应通知，
  rc69/78 静默（B02）；这些不进本函数（执行器直接短路），函数只收「跑完主循环」的 rc。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ClosePolicy(StrEnum):
    STOP_AND_HOME = "stop_and_home"   # rc0 正常收尾：force-stop + HOME
    STAY = "stay"                     # lit2/4：手机停在当前屏等她
    HOME_ONLY = "home_only"           # rc≠0：只按 HOME（B07）


def notify_title(*, rc: int, lit: int | None, done_word: str | None) -> str:
    """推送标题五档（她 10-27 定的口径：不带日期）。"""
    if lit == 2:
        return "PDD 需人工"
    if lit == 4:
        return "PDD 💡"
    if rc == 0:
        if done_word and "已使用" in done_word:
            return "PDD 已使用"
        return "PDD ✅"
    if rc == 6:
        return "PDD ⬛ 退出码 6"
    return f"PDD ❌ 退出码 {rc}"


def ledger_plan(*, lit: int | None, rc: int, pend_days: int | None,
                ledger_current: int | None) -> int | None:
    """账本写入值；None=一个字都不写。

    - lit1/lit2：清 0（正常周期 / 倒数走完）；
    - lit4：屏幕 N 照抄 → 账上正数减 1 → 都没有则不写（旧 pend_pause_write 三分支）；
    - rc0 且 lit∈{0,3}：清 0（兑换倒数作废）；
    - rc≠0：不写（不以失败覆盖账本）。
    """
    if lit == 1 or lit == 2:
        return 0
    if lit == 4:
        if pend_days is not None:
            return pend_days
        if ledger_current is not None and ledger_current > 0:
            return ledger_current - 1
        return None
    if rc == 0 and lit in (0, 3):
        return 0
    return None


@dataclass(frozen=True, slots=True)
class TerminalPlan:
    marker_write: bool
    ledger_write: int | None
    close_policy: ClosePolicy
    notify_title: str
    final_scroll: bool        # rc0 且 lit∈{0,3} 的最终 20 次下滑（I06；lit2/4 绝不滑）


def terminal_plan(*, rc: int, lit: int | None, done_word: str | None = None,
                  pend_days: int | None = None, ledger_current: int | None = None,
                  close_app_on_ok: bool = True,
                  no_close_lit: tuple[int, ...] = (2, 4)) -> TerminalPlan:
    """主循环跑完后的收尾计划。rc 必须是「主循环退出码」（0/4/5/6/7…），早退路径不进这里。"""
    if rc == 0:
        marker = lit in (1, 3, 4) or lit == 0        # rc0&lit0 兼容分支（B05，不可达但保留）
        ledger = ledger_plan(lit=lit, rc=rc, pend_days=pend_days, ledger_current=ledger_current)
        stay = lit in no_close_lit
        close = ClosePolicy.STAY if stay else (
            ClosePolicy.STOP_AND_HOME if close_app_on_ok else ClosePolicy.STAY)
        final_scroll = lit in (0, 3)
        title = notify_title(rc=rc, lit=lit, done_word=done_word)
        return TerminalPlan(marker, ledger, close, title, final_scroll)
    # rc≠0：不写标记、不写账本；收尾只有 HOME（B07）；rc4/5/6/7 各自标题
    title = notify_title(rc=rc, lit=lit, done_word=done_word)
    return TerminalPlan(False, None, ClosePolicy.HOME_ONLY, title, False)
