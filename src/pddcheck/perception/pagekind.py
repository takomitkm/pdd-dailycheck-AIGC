"""页型判定（T18a）：从页面文本特征认出当前在哪一页，供裁片通道选择。

真机实测三类页面的区分特征（2026-11-07）：
  首页    ：推荐/食品/女装/百货/限时秒杀/免费领礼物/9块9特卖（商品瀑布流）
  频道页  ：百亿补贴品质保障/抢低至5折/频道专享/品牌授权/全场5折起
  活动页  ：天内再点亮/必得/共100元券/立即领取/今日已点亮/福袋加码

判定只依赖文本特征，不依赖 activity（活动页与频道页同为 NewPageActivity）。
"""

from __future__ import annotations

from enum import StrEnum

from pddcheck.perception.normalize import normalize


class PageKind(StrEnum):
    HOME = "home"
    CHANNEL = "channel"
    ACTIVITY = "activity"
    UNKNOWN = "unknown"


_HOME = ("推荐", "食品", "女装", "百货", "限时秒杀", "免费领礼物", "9块9特卖", "多多买菜")
_CHANNEL = ("百亿补贴品质保障", "抢低至5折", "频道专享", "品牌授权", "全场5折起", "百亿消费券")
_ACTIVITY = ("天内再点亮", "必得", "共100元券", "立即领取", "今日已点亮", "福袋加码", "点亮")


def classify_page(text: str) -> PageKind:
    """按特征命中数打分；活动页优先于频道页优先于首页（越具体越优先）。"""
    clean = normalize(text)
    scores = {
        PageKind.ACTIVITY: sum(1 for k in _ACTIVITY if normalize(k) in clean),
        PageKind.CHANNEL: sum(1 for k in _CHANNEL if normalize(k) in clean),
        PageKind.HOME: sum(1 for k in _HOME if normalize(k) in clean),
    }
    best = max(scores.values())
    if best == 0:
        return PageKind.UNKNOWN
    for kind in (PageKind.ACTIVITY, PageKind.CHANNEL, PageKind.HOME):
        if scores[kind] == best:
            return kind
    return PageKind.UNKNOWN
