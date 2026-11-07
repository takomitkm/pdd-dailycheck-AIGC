"""T18a：页型判定——用真机实测的三类页面文本特征做判据。"""

from __future__ import annotations

import pytest

from pddcheck.perception.pagekind import PageKind, classify_page

# 真机截图 OCR 文本（2026-11-07，去噪后保留区分特征）
HOME_TEXT = ("推荐 食品 女装 百货 医药 限时秒杀 充值中心 免费领礼物 9块9特卖 "
             "多多买菜 明天自提 已包邮 先用后付 立减10元")
CHANNEL_TEXT = ("百亿补贴品质保障 品牌授权 买贵双倍赔 抢低至5折 频道专享 全场5折起 "
                "百亿消费券 加倍补 极速达")
ACTIVITY_TEXT = ("拼多多首页 点百亿补贴 参与活动 9天内再点亮5次必得 共100元券 "
                 "立即领取 今日已点亮 福袋加码 邀好友抽福袋")

# 真机 OCR 常带噪声（数字/英文/误识字符），判据必须容忍
NOISY_HOME = "511488128RwADs711488128 ARSEie 食品女装Ak百货KRHO医药BE i 限时秒杀 免费Be"
NOISY_CHANNEL = "a 全 Q老干妈老BB x站 Qsme CEARETSA IL11MSH抢低至5折 f频道专享"
NOISY_ACTIVITY = "拼多多首页点百亿补贴参与活动拼多多首页 9天内再点亮5次必得二三二 5折 共100元券"


@pytest.mark.parametrize("text,expected", [
    (HOME_TEXT, PageKind.HOME),
    (CHANNEL_TEXT, PageKind.CHANNEL),
    (ACTIVITY_TEXT, PageKind.ACTIVITY),
    (NOISY_HOME, PageKind.HOME),
    (NOISY_CHANNEL, PageKind.CHANNEL),
    (NOISY_ACTIVITY, PageKind.ACTIVITY),
    ("", PageKind.UNKNOWN),
    ("完全无关的文字", PageKind.UNKNOWN),
])
def test_classify(text, expected):
    assert classify_page(text) is expected


def test_activity_wins_over_channel_when_both_hit():
    """活动页常同时含「百亿补贴」类字样，但活动页特征更具体 → 优先判活动页。"""
    text = "百亿补贴 频道专享 9天内再点亮5次必得 共100元券"
    assert classify_page(text) is PageKind.ACTIVITY


def test_classify_is_normalization_tolerant():
    # 空格/标点被规范化抹掉后仍能命中
    assert classify_page("9 天 内 再 点 亮 5 次 必 得") is PageKind.ACTIVITY
