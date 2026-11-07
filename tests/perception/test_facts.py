"""事实抽取单元测试：进度次数、待兑换天数、各标签识别。"""

from __future__ import annotations

from pddcheck.perception.facts import facts_from_text, read_pend_days, read_progress_count


def test_read_progress_count_wordings():
    assert read_progress_count("9天内点亮4次必得") == 4
    assert read_progress_count("7天内再点亮2次即可") == 2
    assert read_progress_count("立即点亮") is None           # 读不到 ≠ 0
    assert read_progress_count("") is None


def test_read_pend_days():
    assert read_pend_days("点亮任务已完成 3天后可兑换") == 3
    assert read_pend_days("待兑换") is None


def test_facts_labels():
    f = facts_from_text("抽福袋 今日已点亮 9天内点亮4次必得")
    assert f.done_text is not None and f.progress_count == 4
    f = facts_from_text("点亮任务已完成 3天后可兑换")
    assert f.pend_text is not None and f.pend_days == 3
    f = facts_from_text("立即兑换")
    assert f.exchange_text is not None
    f = facts_from_text("恭喜提前锁定限时翻倍券")
    assert f.prize_text is not None
