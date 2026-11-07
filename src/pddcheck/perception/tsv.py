"""Tesseract TSV 解析与合行——finder() 的 run_tsv 分组逻辑移植（pdd.sh:539-566）。

关键兼容怪癖（契约 §3.4，全部显式保留）：
1. 只认 level==5 的词行；列序 = tesseract TSV 标准 12 列；
2. 合行键 = (block_num, par_num, line_num)——psm 11 一字一行、psm 6 一行一词都能拼回行；
3. **每个规范化字符继承它所在词（word）的整框**——不是真实字形框，精度记
   TOKEN_UNION_APPROX；命中 span 的点击点是这些词框并集的中心；
4. 一行的置信度 = 行内**所有**词 conf 的最大值（max-line 规则：弱命中词可以蹭同行
   高置信词过闸——旧漏洞，B 表记录，迁移期保留并在候选上暴露 matched-token conf）；
5. 文本为空或 "-" 的词跳过。
"""

from __future__ import annotations

from dataclasses import dataclass

from pddcheck.perception.normalize import normalize


@dataclass(frozen=True, slots=True)
class TokenBox:
    """一个词：原始文本 + 规范化后每个字符各自继承的词框（l,u,r,d，图像空间）。"""

    raw_text: str
    normalized_text: str
    conf: float
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True, slots=True)
class TextLine:
    key: tuple[int, int, int]           # (block, par, line)
    tokens: tuple[TokenBox, ...]
    normalized_text: str                # 行级规范化串（字符序 = tokens 展开序）
    char_boxes: tuple[tuple[str, tuple[int, int, int, int]], ...]
    max_conf: float
    left: int
    top: int
    right: int
    bottom: int


def _int(cols, i: int, default: int = 0) -> int:
    try:
        return int(cols[i])
    except (ValueError, IndexError):
        return default


def _float(cols, i: int, default: float = 0.0) -> float:
    try:
        return float(cols[i])
    except (ValueError, IndexError):
        return default


def parse_tsv(tsv_text: str) -> tuple[TextLine, ...]:
    """解析 TSV 文本 → 合行后的 TextLine 元组（保持文件顺序）。

    健壮性：坏行进（列不足/非数字坐标或置信度/level 非 5）一律跳过或按 0 处理，
    绝不因单行垃圾抛异常——引擎坏输出不能拖垮整帧（空结果≠错误）。
    """
    lines: dict[tuple[int, int, int], dict] = {}
    order: list[tuple[int, int, int]] = []
    for row in tsv_text.splitlines():
        cols = row.rstrip("\n").split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        text = cols[11].strip()
        if text in ("", "-"):
            continue
        try:
            key = (int(cols[2]), int(cols[3]), int(cols[4]))
        except ValueError:
            continue
        left, top = _int(cols, 6), _int(cols, 7)
        box = (left, top, left + _int(cols, 8), top + _int(cols, 9))
        conf = _float(cols, 10)
        if key not in lines:
            lines[key] = {"tokens": [], "chars": [], "confs": [],
                          "l": 1 << 30, "u": 1 << 30, "r": 0, "d": 0, "raws": []}
            order.append(key)
        e = lines[key]
        e["raws"].append(text)
        e["tokens"].append(TokenBox(raw_text=text, normalized_text=normalize(text),
                                    conf=conf, left=box[0], top=box[1],
                                    right=box[2], bottom=box[3]))
        for ch in normalize(text):
            e["chars"].append((ch, box))
        e["l"] = min(e["l"], box[0])
        e["u"] = min(e["u"], box[1])
        e["r"] = max(e["r"], box[2])
        e["d"] = max(e["d"], box[3])
        e["confs"].append(conf)

    out: list[TextLine] = []
    for key in order:
        e = lines[key]
        out.append(TextLine(
            key=key,
            tokens=tuple(e["tokens"]),
            normalized_text="".join(ch for ch, _ in e["chars"]),
            char_boxes=tuple(e["chars"]),
            max_conf=max(e["confs"]),
            left=e["l"], top=e["u"], right=e["r"], bottom=e["d"],
        ))
    return tuple(out)
