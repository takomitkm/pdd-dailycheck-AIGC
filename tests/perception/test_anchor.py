"""锚点定位（T62/11-13 加固）：用可读锚点文字推算无字图标的候选点。

背景：首页「百亿补贴」是艺术字，OCR 读不稳（psm6 乱码 / psm11 偶发）；
但同页图标行文字稳定可读 → 认锚点 + 偏移推算。
安全不变量：认不到锚点 → 空列表（绝不盲点）。
"""

from __future__ import annotations

from pddcheck.perception.anchor import (
    AnchorWord,
    anchor_candidates,
    words_from_tsv,
)


def _tsv_row(text: str, left: int, top: int, w: int, h: int, conf: float = 90.0,
             block: int = 1, par: int = 1, line: int = 1) -> str:
    return (f"5\t{block}\t{par}\t{line}\t1\t-1\t{left}\t{top}\t{w}\t{h}"
            f"\t{conf}\t{text}")


def test_no_anchor_returns_no_candidates():
    """认不到锚点 → 空列表（绝不盲点）。"""
    words = [AnchorWord("推荐", 30, 190, 40, 20)]
    out = anchor_candidates(words, anchors=("限时秒杀",), offsets=((0.0, 0.2),),
                            scale_w=720, scale_h=1280)
    assert out == []


def test_anchor_offset_produces_expected_point():
    """锚点文字 → 偏移 → 候选点（比例口径）。"""
    words = [AnchorWord("限时秒杀", 36, 452, 73, 17)]
    out = anchor_candidates(words, anchors=("限时秒杀",),
                            offsets=((0.0, 0.25),), scale_w=720, scale_h=1280)
    assert len(out) == 1
    # x = 36 + 0.0*720 = 36；y = 452 + 0.25*1280 = 772
    assert out[0].tap_point == (36, 772)
    assert "限时秒杀" in out[0].why


def test_multiple_offsets_give_multiple_candidates_in_order():
    words = [AnchorWord("充值中心", 180, 452, 76, 17)]
    out = anchor_candidates(words, anchors=("充值中心",),
                            offsets=((0.0, 0.20), (0.0, 0.26)),
                            scale_w=720, scale_h=1280)
    assert [c.tap_point[1] for c in out] == [708, 785]
    assert [c.offset for c in out] == [(0.0, 0.20), (0.0, 0.26)]


def test_candidates_outside_screen_are_dropped():
    words = [AnchorWord("限时秒杀", 36, 452, 73, 17)]
    out = anchor_candidates(words, anchors=("限时秒杀",), offsets=((0.0, 5.0),),
                            scale_w=720, scale_h=1280)
    assert out == []


def test_max_candidates_caps():
    words = [AnchorWord("限时秒杀", 36, 452, 73, 17)]
    out = anchor_candidates(words, anchors=("限时秒杀",),
                            offsets=tuple((0.0, 0.1 * i) for i in range(1, 9)),
                            scale_w=720, scale_h=1280, max_candidates=3)
    assert len(out) == 3


def test_same_row_words_deduplicated():
    """psm11 一字一行 → 同一行只取一个锚点（否则一排字会算出 N 个重复候选）。"""
    words = [AnchorWord("限时", 36, 452, 35, 17), AnchorWord("秒杀", 73, 452, 36, 17)]
    out = anchor_candidates(words, anchors=("限时秒杀", "限时", "秒杀"),
                            offsets=((0.0, 0.25),), scale_w=720, scale_h=1280)
    assert len(out) == 1


def test_words_from_tsv_extracts_lines_with_boxes():
    """从 TSV 抽词行（含外框）：合行后的行文本与坐标。"""
    tsv = "\n".join([
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
        _tsv_row("限时", 36, 452, 35, 17, line=1),
        _tsv_row("秒杀", 73, 452, 36, 17, line=1),   # 同一行 → 合行
        _tsv_row("充值", 180, 452, 73, 17, block=2, line=2),
    ])
    words = words_from_tsv([tsv], min_conf=40.0)
    texts = sorted(w.text for w in words)
    assert "限时秒杀" in texts
    assert "充值" in texts
    w = next(w for w in words if w.text == "限时秒杀")
    assert (w.x, w.y, w.w, w.h) == (36, 452, 73, 17)


def test_words_from_tsv_skips_low_conf():
    tsv = "\n".join([
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
        _tsv_row("噪声", 10, 20, 30, 12, conf=12.0, line=1),
        _tsv_row("限时秒杀", 36, 452, 73, 17, conf=95.0, line=2),
    ])
    words = words_from_tsv([tsv], min_conf=40.0)
    assert [w.text for w in words] == ["限时秒杀"]
