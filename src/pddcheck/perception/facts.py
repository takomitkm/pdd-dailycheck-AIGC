"""从一次共享观察里抽取流程事实（事实层，纯函数）。

进度行口径（旧 light_count）：屏幕上「N天内点亮M次必得」/「M天内点亮X次」里的
**剩余次数**；以及 done/exchange/pend/prize 的字样存在性。全部基于 perception 的
规范化文本，不改写 OCR 原文，只产出结构化事实。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pddcheck.perception.normalize import normalize

# 10-16 措辞变更两种都认；抓「点亮」前后的数字
_COUNT = re.compile(r"(\d+)天内点亮(\d+)次|点亮(\d+)次必得|再点亮(\d+)次")


@dataclass(frozen=True, slots=True)
class ScreenFacts:
    progress_count: int | None
    done_text: str | None
    exchange_text: str | None
    pend_text: str | None
    prize_text: str | None
    pend_days: int | None
    pend_line: str | None


def read_progress_count(text: str) -> int | None:
    """从整帧 OCR 文本里读「剩余次数」；读不到 → None（不是 0）。"""
    clean = normalize(text)
    m = _COUNT.search(clean)
    if not m:
        return None
    for g in (m.group(2), m.group(3), m.group(4)):
        if g is not None:
            return int(g)
    return None


def read_pend_days(text: str) -> int | None:
    clean = normalize(text)
    m = re.search(r"(\d+)天后可兑换", clean)
    return int(m.group(1)) if m else None


def facts_from_text(ocr_text: str, *, done_label: str = "今日已点亮",
                    exchange_label: str = "立即兑换", pend_label: str = "待兑换",
                    prize_label: str = "恭喜提前锁定") -> ScreenFacts:
    clean = normalize(ocr_text)
    # 待兑换页有多种措辞：待兑换 / 点亮任务已完成 / N天后可兑换——任一即判 pend
    pend_present = any(normalize(p) in clean for p in
                       (pend_label, "点亮任务已完成", "天后可兑换", "券已放进口袋"))
    return ScreenFacts(
        progress_count=read_progress_count(ocr_text),
        done_text=done_label if normalize(done_label) in clean else None,
        exchange_text=exchange_label if normalize(exchange_label) in clean else None,
        pend_text=pend_label if pend_present else None,
        prize_text=prize_label if normalize(prize_label) in clean else None,
        pend_days=read_pend_days(ocr_text),
        pend_line=None,
    )
