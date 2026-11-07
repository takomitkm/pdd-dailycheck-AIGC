"""同帧共享观察（T16）：把「每目标各跑一遍」变成「每帧每通道只跑一次」。

结构：
  ObservationSource（生产=device+vision，测试=fake）：
    fetch_xml()            一次
    fetch_ocr(source)      每个通道一次（band/pill 的内部多 psm 由引擎批量完成，
                           这里计为 1 次通道调用；调用计数按通道而非 psm，见 callcount 模型）
  observe_frame(...) -> FrameObservation      只调用上述接口，每通道至多一次
  locate_all(obs, specs) -> {key: LocateResult}  从同一观察定位所有目标，不再取数

语义保证：locate_all 与旧「每目标 locate_candidates」逐目标结果一致——它内部就是
用同一批文本构造 ParsedFrame 再调 locate_candidates，差异只在「取数次数」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from pddcheck.domain import CoordinateSource, LocateResult
from pddcheck.perception.locate import (
    ParsedFrame,
    TargetLocateSpec,
    locate_candidates,
)
from pddcheck.perception.ocr_pass import OcrPassInput


class XmlPolicy(StrEnum):
    ALWAYS = "always"
    SKIP = "skip"        # 已知无可用层级的页（如消费券页）省掉一次 dump


def xml_policy_for(page_kind: str) -> XmlPolicy:
    """按页类型决定是否取 XML。消费券/浏览页层级常常整块空或残缺，跳过省调用。"""
    return XmlPolicy.SKIP if page_kind in ("browse", "coupon") else XmlPolicy.ALWAYS


class ObservationSource(Protocol):
    def fetch_xml(self) -> str | None: ...
    def fetch_ocr(self, source: CoordinateSource) -> str | None: ...


@dataclass(frozen=True, slots=True)
class FrameObservation:
    frame_id: str
    capture_id: str
    state_epoch: int
    tap_width: int
    tap_height: int
    xml_text: str | None = None
    ocr_texts: dict[CoordinateSource, str] = field(default_factory=dict)
    # 每个 OCR 通道的几何 (scale_x, scale_y, offset_x, offset_y)：
    # 整页=(1,1,0,0)；band/pill 是裁片放大后的图，必须带缩放与原点偏移，
    # 否则裁片坐标会被当成整页坐标（旧脚本踩过这个坑，见 band_pass 注释）。
    geometries: dict[CoordinateSource, tuple[float, float, float, float]] = field(
        default_factory=dict)
    fetch_calls: tuple[str, ...] = ()          # 实际取数记录（供计数断言）

    def to_parsed_frame(self) -> ParsedFrame:
        passes = []
        for src, text in self.ocr_texts.items():
            if text is None:
                continue
            sx, sy, ox, oy = self.geometries.get(src, (1.0, 1.0, 0.0, 0.0))
            passes.append(OcrPassInput(source=src, tsv_text=text,
                                       scale_x=sx, scale_y=sy, offset_x=ox, offset_y=oy))
        return ParsedFrame(self.frame_id, self.capture_id, self.state_epoch,
                           self.tap_width, self.tap_height,
                           xml_text=self.xml_text, ocr_passes=tuple(passes))


def observe_frame(source: ObservationSource, *, frame_id: str, capture_id: str,
                  state_epoch: int, tap_width: int, tap_height: int,
                  channels: tuple[CoordinateSource, ...],
                  xml_policy: XmlPolicy = XmlPolicy.ALWAYS) -> FrameObservation:
    """取一次 XML（除非策略跳过）+ 每个通道取一次 OCR。同通道绝不重复取。"""
    calls: list[str] = []
    xml_text = None
    if xml_policy is XmlPolicy.ALWAYS:
        xml_text = source.fetch_xml()
        calls.append("xml")
    ocr: dict[CoordinateSource, str] = {}
    geometries: dict[CoordinateSource, tuple[float, float, float, float]] = {}
    geometry_for = getattr(source, "geometry_for", None)
    for src in channels:
        if src in ocr:
            raise ValueError(f"通道 {src} 重复请求（应每通道只取一次）")
        text = source.fetch_ocr(src)
        if text is not None:
            ocr[src] = text
            if geometry_for is not None:
                g = geometry_for(src)
                if g is not None:
                    geometries[src] = tuple(float(v) for v in g)
        calls.append(f"ocr:{src.value}")
    return FrameObservation(frame_id, capture_id, state_epoch, tap_width, tap_height,
                            xml_text=xml_text, ocr_texts=ocr, geometries=geometries,
                            fetch_calls=tuple(calls))


def locate_all(obs: FrameObservation, specs: dict[str, TargetLocateSpec], *,
               min_conf: int) -> dict[str, LocateResult]:
    """从同一观察定位所有目标——不再触发任何取数。"""
    frame = obs.to_parsed_frame()
    return {key: locate_candidates(frame, spec, min_conf=min_conf)
            for key, spec in specs.items()}
