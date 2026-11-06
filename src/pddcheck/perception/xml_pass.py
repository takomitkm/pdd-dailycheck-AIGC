"""XML 通道候选：finder() 的 run_xml/score_of 移植（pdd.sh:499-536）。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from pddcheck.domain import BoxPrecision, Candidate, CoordinateSource, Rect
from pddcheck.perception.geometry_map import emit_point
from pddcheck.perception.lcs import longest_common_span
from pddcheck.perception.normalize import normalize

BOUNDS = re.compile(r"\[\s*(\d+)\s*,\s*(\d+)\s*\]\[\s*(\d+)\s*,\s*(\d+)\s*\]")
_FIELDS = ("text", "content-desc", "resource-id")


@dataclass(frozen=True, slots=True)
class XmlNode:
    text: str
    content_desc: str
    resource_id: str
    clickable: bool
    left: int
    top: int
    right: int
    bottom: int


def parse_xml(xml_text: str) -> tuple[XmlNode, ...]:
    """ET 优先，坏 XML 退回属性正则（旧 nodes() 的双路，容忍半截层级）。"""
    try:
        root = ET.fromstring(xml_text)
        nodes = []
        for e in root.iter("node"):
            a = e.attrib
            m = BOUNDS.search(a.get("bounds") or "")
            if not m:
                continue
            x1, y1, x2, y2 = (int(g) for g in m.groups())
            nodes.append(XmlNode(a.get("text") or "", a.get("content-desc") or "",
                                 a.get("resource-id") or "",
                                 a.get("clickable") == "true", x1, y1, x2, y2))
        return tuple(nodes)
    except ET.ParseError:
        nodes = []
        for m in re.finditer(r"<node\b([^>]*?)/?>", xml_text):
            attrs = dict(re.findall(r'([\w:.-]+)="([^"]*)"', m.group(1)))
            b = BOUNDS.search(attrs.get("bounds") or "")
            if not b:
                continue
            x1, y1, x2, y2 = (int(g) for g in b.groups())
            nodes.append(XmlNode(attrs.get("text") or "", attrs.get("content-desc") or "",
                                 attrs.get("resource-id") or "",
                                 attrs.get("clickable") == "true", x1, y1, x2, y2))
        return tuple(nodes)


def xml_pass_candidates(
    frame_id: str,
    capture_id: str,
    state_epoch: int,
    xml_text: str,
    key: str,
    labels: tuple[str, ...],
    *,
    min_overlap: int,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    rank_from: int = 0,
) -> tuple[Candidate, ...]:
    """一次 XML 通道 → 有序候选。

    兼容怪癖（保留）：
    - 字段顺序 text → content-desc → resource-id，节点在**第一个能打分的字段**上出候选；
    - resource-id 的打分是「label 是否在**原始**串里」，命中分 = len(label)；
    - 排序 = (-score, 非 clickable 靠后)，并列保持节点顺序；
    - 点击点 = 节点框中心（float），emit 截断；精度 ELEMENT。
    """
    labels_norm = [normalize(lb) for lb in labels]
    hits: list[tuple[int, bool, float, float, str, str, XmlNode]] = []
    for n in parse_xml(xml_text):
        for field in _FIELDS:
            value = {"text": n.text, "content-desc": n.content_desc,
                     "resource-id": n.resource_id}[field]
            clean = normalize(value)
            best: tuple[str, int] | None = None
            for lb_raw, lb in zip(labels, labels_norm):
                if field == "resource-id":
                    sc = len(lb) if lb_raw in value else 0
                else:
                    sc = longest_common_span(clean, lb)[0] if clean else 0
                if sc >= min_overlap and (best is None or sc > best[1]):
                    best = (lb_raw, sc)
            if best is not None:
                cx, cy = (n.left + n.right) / 2, (n.top + n.bottom) / 2
                hits.append((best[1], n.clickable, cx, cy, value, field, n))
                break
    hits.sort(key=lambda h: (-h[0], not h[1]))
    out: list[Candidate] = []
    for rank, (sc, _clk, cx, cy, value, field, node) in enumerate(hits, start=rank_from):
        tx, ty = emit_point(cx, cy, scale_x, scale_y, offset_x, offset_y)
        out.append(Candidate(
            candidate_id=f"{frame_id}:xml:{rank}",
            capture_id=capture_id,
            state_epoch=state_epoch,
            key=key,
            source=CoordinateSource.XML,
            overlap=sc,
            rank_in_pass=rank,
            matched_text=" ".join(value.split())[:48],
            tap_point=(tx, ty),
            box=Rect(node.left, node.top, node.right - node.left, node.bottom - node.top),
            box_precision=BoxPrecision.ELEMENT,
            reading_ref=None,
            rejection_reasons=(),
        ))
    return tuple(out)
