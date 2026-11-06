"""OCR 通道候选：run_tsv 的打分与 span→点击点移植（pdd.sh:567-591）。"""

from __future__ import annotations

from dataclasses import dataclass

from pddcheck.domain import BoxPrecision, Candidate, CoordinateSource
from pddcheck.perception.geometry_map import emit_point
from pddcheck.perception.lcs import longest_common_span
from pddcheck.perception.normalize import normalize
from pddcheck.perception.tsv import parse_tsv


@dataclass(frozen=True, slots=True)
class OcrPassInput:
    """一次 OCR 通道的输入：TSV 文本 + 该通道的几何（整页=1.0/0,0；band/pill=放大与偏移）。"""

    source: CoordinateSource            # TESSERACT_PAGE | BAND | PILL
    tsv_text: str
    scale_x: float = 1.0
    scale_y: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    reading_ref: str = ""
    engine_id: str = "tesseract-cli"
    engine_version: str | None = None
    model_hash: str | None = None


def ocr_pass_candidates(
    frame_id: str,
    capture_id: str,
    state_epoch: int,
    pass_input: OcrPassInput,
    key: str,
    labels: tuple[str, ...],
    *,
    min_overlap: int,
    min_conf: int,
    rank_from: int = 0,
) -> tuple[Candidate, ...]:
    """一条 OCR 通道 → 有序候选（行内 overlap 降序；并列保持行序）。

    key 属主目标：legacy 是每目标各跑一遍通道；跨目标共享由上层观察缓存做，
    本函数保持逐目标语义。

    - 行资格：max(行内所有词 conf) >= min_conf（max-line 规则，兼容保留）；
    - 命中 span 的点击点 = span 字符对应词框并集的中心，emit 截断映射到点空间；
    - 每个候选带 reading_ref 与 engine 元数据（契约：OCR 来源必带）。
    """
    labels_norm = [normalize(lb) for lb in labels]
    labels_norm = [lb for lb in labels_norm if lb]
    rows: list[tuple[int, int, str]] = []        # (overlap, line_index, line_key)
    parsed = parse_tsv(pass_input.tsv_text)
    for idx, line in enumerate(parsed):
        if line.max_conf < min_conf:
            continue
        best: tuple[int, int] | None = None      # (overlap, at)
        for lb_raw, lb in zip(labels, labels_norm):
            sc, at = longest_common_span(line.normalized_text, lb)
            if sc >= min_overlap and (best is None or sc > best[0]):
                best = (sc, at)
        if best is not None:
            rows.append((best[0], idx, "x"))
    # 旧行为：整通道按 overlap 降序重排（hits.sort(key=-sc)），并列保持行序（sort 稳定）
    rows.sort(key=lambda r: -r[0])
    out: list[Candidate] = []
    for rank, (sc, idx, _k) in enumerate(rows, start=rank_from):
        line = parsed[idx]
        at = None
        for lb_raw, lb in zip(labels, labels_norm):
            s2, a2 = longest_common_span(line.normalized_text, lb)
            if s2 == sc:
                at = a2
                break
        assert at is not None
        span_boxes = [box for ch, box in line.char_boxes[at:at + sc]]
        if not span_boxes:                            # 理论不可达（sc>=1 必有字符）
            continue
        l = min(b[0] for b in span_boxes)
        u = min(b[1] for b in span_boxes)
        r = max(b[2] for b in span_boxes)
        d = max(b[3] for b in span_boxes)
        cx, cy = (l + r) / 2, (u + d) / 2
        tx, ty = emit_point(cx, cy, pass_input.scale_x, pass_input.scale_y,
                            pass_input.offset_x, pass_input.offset_y)
        raw_value = " ".join(line_key_raw(line).split())[:48]
        out.append(Candidate(
            candidate_id=f"{frame_id}:{pass_input.source.value}:{rank}",
            capture_id=capture_id,
            state_epoch=state_epoch,
            key=key,
            source=pass_input.source,
            overlap=sc,
            rank_in_pass=rank,
            matched_text=raw_value,
            tap_point=(tx, ty),
            box=None,                                  # 通道几何已折进 tap_point；框留给 XML/ELEMENT
            box_precision=None,
            engine_id=pass_input.engine_id,
            engine_version=pass_input.engine_version,
            model_hash=pass_input.model_hash,
            reading_ref=pass_input.reading_ref or f"ocr/{frame_id}/{pass_input.source.value}",
            rejection_reasons=(),
        ))
    return tuple(out)


def line_key_raw(line) -> str:
    """行内各词原文拼接（旧 value = ' '.join(e['raw'])）。"""
    return " ".join(t.raw_text for t in line.tokens)
