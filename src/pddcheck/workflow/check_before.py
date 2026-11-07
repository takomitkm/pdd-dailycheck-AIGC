"""点「立即点亮」之前的终态决策核（T11）——cmd_run L1556-1572 的纯函数化。

只有站在点亮那一屏上才判（首页信息流里的「已使用」三个字不算——旧注释口径）。
判据优先级与旧一致：done → exchange → pend → 读点前进度（读不到=照点，before=None）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CheckBeforeKind(StrEnum):
    DONE = "done"            # → lit1，DONE_WORD 抄屏幕
    EXCHANGE = "exchange"    # → lit2，人工兑换
    PENDING = "pending"      # → lit4
    PROCEED = "proceed"      # 照常点亮，before=点前进度（None=读不到）


@dataclass(frozen=True, slots=True)
class CheckBeforeOutcome:
    kind: CheckBeforeKind
    lit: int | None = None           # 1/2/4；PROCEED 为 None
    done_word: str | None = None     # lit1 时屏幕上抄到的字（推送标题分支用）
    before_count: int | None = None  # PROCEED 时点前进度（None=读不到）


def check_done_before_decision(
    *,
    done_text: str | None,
    exchange_text: str | None,
    pend_text: str | None,
    before_count: int | None,
) -> CheckBeforeOutcome:
    """done/exchange/pend 传「屏幕上读到的字样」（None=没读到）。"""
    if done_text is not None:
        return CheckBeforeOutcome(CheckBeforeKind.DONE, lit=1, done_word=done_text)
    if exchange_text is not None:
        return CheckBeforeOutcome(CheckBeforeKind.EXCHANGE, lit=2)
    if pend_text is not None:
        return CheckBeforeOutcome(CheckBeforeKind.PENDING, lit=4)
    return CheckBeforeOutcome(CheckBeforeKind.PROCEED, before_count=before_count)
