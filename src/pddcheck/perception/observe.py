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
from typing import Protocol

from pddcheck.domain import CoordinateSource, LocateResult
from pddcheck.perception.locate import (
    ParsedFrame,
    TargetLocateSpec,
    locate_candidates,
)
from pddcheck.perception.ocr_pass import OcrPassInput


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
    fetch_calls: tuple[str, ...] = ()          # 实际取数记录（供计数断言）

    def to_parsed_frame(self) -> ParsedFrame:
        passes = tuple(OcrPassInput(source=src, tsv_text=text)
                       for src, text in self.ocr_texts.items() if text is not None)
        return ParsedFrame(self.frame_id, self.capture_id, self.state_epoch,
                           self.tap_width, self.tap_height,
                           xml_text=self.xml_text, ocr_passes=passes)


def observe_frame(source: ObservationSource, *, frame_id: str, capture_id: str,
                  state_epoch: int, tap_width: int, tap_height: int,
                  channels: tuple[CoordinateSource, ...]) -> FrameObservation:
    """取一次 XML + 每个通道取一次 OCR。同一通道绝不重复取（重复=编程错误）。"""
    calls: list[str] = []
    xml_text = source.fetch_xml()
    calls.append("xml")
    ocr: dict[CoordinateSource, str] = {}
    for src in channels:
        if src in ocr:
            raise ValueError(f"通道 {src} 重复请求（应每通道只取一次）")
        text = source.fetch_ocr(src)
        if text is not None:
            ocr[src] = text
        calls.append(f"ocr:{src.value}")
    return FrameObservation(frame_id, capture_id, state_epoch, tap_width, tap_height,
                            xml_text=xml_text, ocr_texts=ocr, fetch_calls=tuple(calls))


def locate_all(obs: FrameObservation, specs: dict[str, TargetLocateSpec], *,
               min_conf: int) -> dict[str, LocateResult]:
    """从同一观察定位所有目标——不再触发任何取数。"""
    frame = obs.to_parsed_frame()
    return {key: locate_candidates(frame, spec, min_conf=min_conf)
            for key, spec in specs.items()}
