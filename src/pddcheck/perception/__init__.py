"""perception：定位纯函数（T12）——从 pdd.sh finder()/pick()/in_region() 逐条移植。

这里没有任何 IO/设备/OCR 进程：输入是已采集的 XML 文本与 TSV 文本，输出是
domain.Candidate 的有序候选。所有与旧行为的兼容怪癖都显式注释（契约 §3.4）。
"""

from pddcheck.perception.geometry_map import scale_5dp, emit_point
from pddcheck.perception.lcs import longest_common_span
from pddcheck.perception.locate import ParsedFrame, TargetLocateSpec, locate_candidates
from pddcheck.perception.normalize import normalize
from pddcheck.perception.observe import (
    FrameObservation,
    ObservationSource,
    locate_all,
    observe_frame,
)
from pddcheck.perception.ocr_pass import OcrPassInput, ocr_pass_candidates
from pddcheck.perception.tsv import parse_tsv
from pddcheck.perception.xml_pass import xml_pass_candidates

__all__ = [
    "normalize",
    "longest_common_span",
    "parse_tsv",
    "OcrPassInput",
    "ocr_pass_candidates",
    "xml_pass_candidates",
    "locate_candidates",
    "scale_5dp",
    "emit_point",
    "ParsedFrame",
    "TargetLocateSpec",
    "FrameObservation",
    "ObservationSource",
    "observe_frame",
    "locate_all",
]
