"""锚点定位（迁移加固 T62）：用**可读文字**推算无字图标的点击点。

背景（11-10/11-11/11-13 真机实测）：
- 首页「百亿补贴」是**艺术字图标**：psm6 读成乱码，psm11 也只是偶发读到
  （11-13 同一张图一次 conf 81、另两次读成 'SEAM' conf 38）→ 不可依赖。
- 但同页那排**图标文字**（「限时秒杀/充值中心/免费领礼物/多多果园/其他」）**高度稳定**
  （conf 85~97），且「百亿补贴」卡片恒在图标行下方、与图标行**同列**（最左一格）。

本模块的做法：认到锚点文字 → 按 (dx, dy) 偏移算出目标图标位置 → 给出一串候选点。
调用方逐个试点，用**落地页校验**（认到「抽福袋/搜低价/精选+奢品馆」）判成功，
不成功就 BACK 再试下一个候选（pdd.sh 的精神：点错就退，不拿分数=0 的盲点冒充成功）。

安全不变量：
- 认不到锚点 → 返回空列表，**绝不返回盲点**（10-11 的 rc=5 就是盲点坐标惹的）；
- 候选点只是「可能的位置」，是否真的点对由调用方的落地校验裁决；
- 偏移量用**屏幕比例**（相对锚点文字框的宽/高），跟随真实分辨率。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnchorWord:
    """锚点文字的一个词行（点空间像素）。"""
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


@dataclass(frozen=True, slots=True)
class AnchorCandidate:
    """一个推算出来的候选点击点。"""
    x: int
    y: int
    anchor_text: str
    offset: tuple[float, float]      # (dx, dy) 屏幕比例（相对锚点框）
    why: str                          # 来源说明（进日志/notes）

    @property
    def tap_point(self) -> tuple[int, int]:
        return (self.x, self.y)


def anchor_candidates(words: list[AnchorWord], *, anchors: tuple[str, ...],
                      offsets: tuple[tuple[float, float], ...],
                      scale_w: int, scale_h: int,
                      max_candidates: int = 6) -> list[AnchorCandidate]:
    """按锚点文字推算候选点。

    anchors：锚点词（任一命中即用；同一锚点可有多个偏移 → 多个候选）。
    offsets：(dx, dy) 屏幕比例，相对**锚点文字框左上角**的偏移（可负）。
    scale_w/scale_h：点空间尺寸（用来把比例换算成像素）。

    顺序：按锚点在页面里**从上到下**（更靠上的锚点通常更接近目标），
    同一锚点内按 offsets 顺序（先近后远）。总数受 max_candidates 限制。
    """
    if scale_w <= 0 or scale_h <= 0:
        return []
    hits: list[tuple[int, int, AnchorWord]] = []
    for w in words:
        clean = w.text.replace(" ", "")
        for a in anchors:
            if a in clean:
                # 记录「匹配长度」：同一个 y 上可能有合并行（整排图标文字合一行）与
                # 单词行；**更精确（更短）的匹配优先**——合并行的 x 是最左，
                # 而我们要的是某一格自己的 x（11-13 真机：图标行被合行后 x=36..670，
                # 直接用会让所有候选都落在最左列）。
                hits.append((len(a), w.y, w))
                break
    if not hits:
        return []
    # 同一排（±24px，容纳 OCR 逐字切分与合并行的 y 抖动）只留一个锚点，
    # 且**同一排内优先更短（更精确）的匹配**——合并行往往是「整排图标文字 + 乱码」
    # 拼一起，用它算 x 会偏、且会多出一串重复候选（11-13 真机实测）。
    by_row: dict[int, tuple[int, int, AnchorWord]] = {}
    for alen, y, w in hits:
        key = y // 24
        cur = by_row.get(key)
        if cur is None or alen < cur[0]:
            by_row[key] = (alen, y, w)
    picked = [v[2] for v in sorted(by_row.values(), key=lambda t: t[1])]
    out: list[AnchorCandidate] = []
    for w in picked:
        for dx, dy in offsets:
            x = int(round(w.x + dx * scale_w))
            y = int(round(w.y + dy * scale_h))
            if not (0 <= x < scale_w and 0 <= y < scale_h):
                continue
            out.append(AnchorCandidate(
                x=x, y=y, anchor_text=w.text, offset=(dx, dy),
                why=f"锚点「{w.text}」@({w.x},{w.y}) + 偏移({dx:.3f},{dy:.3f})"))
            if len(out) >= max_candidates:
                return out
    return out


def words_from_tsv(tsv_texts: list[str], *, min_conf: float = 40.0) -> list[AnchorWord]:
    """从若干通道的 TSV 文本里抽词行（当锚点用）。

    只取 level==5 的词行（与旧 finder 同口径）；合行后的行文本与外框取自
    perception.tsv.parse_tsv —— 同一行的字（psm 11 一字一行）会并成一行，
    所以「限时秒杀」这种两字词能被完整认到（conf 取行内最大值）。
    """
    from pddcheck.perception.tsv import parse_tsv
    out: list[AnchorWord] = []
    seen: set[tuple[int, int, int, int]] = set()
    for text in tsv_texts:
        if not text:
            continue
        for line in parse_tsv(text):
            if not line.normalized_text:
                continue
            if line.max_conf < min_conf:
                continue
            key = (line.left, line.top, line.right, line.bottom)
            if key in seen:
                continue
            seen.add(key)
            out.append(AnchorWord(text=line.normalized_text, x=line.left, y=line.top,
                                  w=line.right - line.left, h=line.bottom - line.top))
    return out
