"""定位装配：多通道候选 + region 闸 + 坐标兜底 → LocateResult（T12 核心）。

兼容语义（逐条对应旧 pick()/in_region()/find_target 的坐标兜底）：
- 通道按调用方给定的顺序参与（legacy = xml → 整页 psm11 → 整页 psm6 → band → pill），
  **winner = 第一个落进 REGION 的候选**，不是全局最高分（pick() 文件序语义）；
- REGION 为空 = 不设闸（旧 in_region 对空 spec 直接 return 0）；闸是双闭区间
  [x1*W, x2*W] × [y1*H, y2*H]，对**点空间**（tap_w/tap_h）；
- 区外候选保留在 ordered 里并标 rejection=out_of_region（旧只打 WARN，新程序留痕）；
- 坐标兜底：labels 命中全失败且 spec 允许时，产生 CONFIG_COORD 候选，
  tap = int(f*W+0.5)（正数 round-half-up，旧 frac_x/frac_y；与 OCR 的截断是两类舍入）；
  点空间未知（tap_w/h<=0）时兜底不可用 → NO_MATCH + 原因（旧 frac_xy 失败路径）。
"""

from __future__ import annotations

from dataclasses import dataclass

from pddcheck.domain import (
    Candidate,
    CoordinateSource,
    LocateResult,
    LocateStatus,
)
from pddcheck.perception.ocr_pass import OcrPassInput, ocr_pass_candidates
from pddcheck.perception.xml_pass import xml_pass_candidates


@dataclass(frozen=True, slots=True)
class ParsedFrame:
    """一次采集的最小定位输入（由调用方从 Capture/工件组装）。"""

    frame_id: str
    capture_id: str
    state_epoch: int
    tap_width: int
    tap_height: int
    xml_text: str | None = None
    ocr_passes: tuple[OcrPassInput, ...] = ()


@dataclass(frozen=True, slots=True)
class TargetLocateSpec:
    key: str
    labels: tuple[str, ...]
    min_overlap: int
    region: tuple[float, float, float, float] | None = None
    coord: tuple[float, float] | None = None
    allow_coord: bool = True


def _in_region(px: int, py: int, region: tuple[float, float, float, float] | None,
               tap_w: int, tap_h: int) -> bool:
    if region is None:
        return True
    x1, y1, x2, y2 = region
    return (x1 * tap_w <= px <= x2 * tap_w) and (y1 * tap_h <= py <= y2 * tap_h)


def locate_candidates(
    frame: ParsedFrame,
    spec: TargetLocateSpec,
    *,
    min_conf: int,
) -> LocateResult:
    """按给定通道序定位一个目标。winner=第一个入区候选；否则按 spec 决定坐标兜底。"""
    ordered: list[Candidate] = []
    labels = spec.labels

    if frame.xml_text is not None:
        ordered.extend(xml_pass_candidates(
            frame.frame_id, frame.capture_id, frame.state_epoch, frame.xml_text,
            spec.key, labels, min_overlap=spec.min_overlap))

    rank_from = len(ordered)
    for ps in frame.ocr_passes:
        if not isinstance(ps, OcrPassInput):  # 防呆：调用方传错序
            raise TypeError("ocr_passes 里混入了非 OcrPassInput")
        ordered.extend(ocr_pass_candidates(
            frame.frame_id, frame.capture_id, frame.state_epoch, ps,
            spec.key, labels, min_overlap=spec.min_overlap, min_conf=min_conf,
            rank_from=rank_from))
        rank_from = len(ordered)

    winner: Candidate | None = None
    rejected = 0
    for cand in ordered:
        assert cand.tap_point is not None
        if _in_region(cand.tap_point[0], cand.tap_point[1], spec.region,
                      frame.tap_width, frame.tap_height):
            winner = cand
            break
        rejected += 1
        # 不可变对象：重建一份带拒绝原因的候选（旧版只打 WARN，这里留进候选本身）
        ordered[ordered.index(cand)] = _with_rejection(cand, "out_of_region")

    if winner is None and spec.allow_coord and spec.coord is not None:
        if frame.tap_width <= 0 or frame.tap_height <= 0:
            return LocateResult(
                LocateStatus.NO_MATCH, frame.capture_id, spec.key, 0,
                ordered=tuple(ordered), error_code="geometry_unknown")
        fx, fy = spec.coord
        tap = (int(fx * frame.tap_width + 0.5), int(fy * frame.tap_height + 0.5))
        winner = Candidate(
            candidate_id=f"{frame.frame_id}:coord",
            capture_id=frame.capture_id,
            state_epoch=frame.state_epoch,
            key=spec.key,
            source=CoordinateSource.CONFIG_COORD,
            overlap=0,
            rank_in_pass=len(ordered),
            tap_point=tap,
            rejection_reasons=(),
        )
        ordered = (*ordered, winner)

    if winner is not None:
        return LocateResult(
            LocateStatus.MATCH, frame.capture_id, spec.key, 0,
            winning=winner, ordered=tuple(ordered))
    reasons: tuple[Candidate, ...] = tuple(ordered)
    return LocateResult(
        LocateStatus.NO_MATCH, frame.capture_id, spec.key, 0,
        ordered=reasons)


def _with_rejection(cand: Candidate, reason: str) -> Candidate:
    return Candidate(
        candidate_id=cand.candidate_id,
        capture_id=cand.capture_id,
        state_epoch=cand.state_epoch,
        key=cand.key,
        source=cand.source,
        overlap=cand.overlap,
        rank_in_pass=cand.rank_in_pass,
        matched_text=cand.matched_text,
        tap_point=cand.tap_point,
        box=cand.box,
        box_precision=cand.box_precision,
        engine_id=cand.engine_id,
        engine_version=cand.engine_version,
        model_hash=cand.model_hash,
        reading_ref=cand.reading_ref,
        rejection_reasons=(*cand.rejection_reasons, reason),
    )
