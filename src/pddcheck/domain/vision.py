"""视觉候选：recipe、文本 token、候选与定位结果（契约 §3.4）。

关键语义（迁移不得破坏）：
- overlap 是「最长公共连续字符段长度」，不是 LCS 子序列，也不是概率；
- match_overlap 与置信度不同域：Tesseract 0..100、RapidOCR 0..1，不混算；
- 旧 TSV matcher 的字框是「所属 TSV word 的框」的近似，标 TOKEN_UNION_APPROX，
  不得宣称真实字形框；
- CONFIG_COORD 是无识别文本的独立候选来源，不能充当 text_present 证据。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from pddcheck.domain.errors import InvalidDomain
from pddcheck.domain.geometry import Rect
from pddcheck.domain.jsonio import serializable, strict_fields
from pddcheck.domain.validate import (
    require_enum,
    require_int,
    require_no_duplicates,
    require_str,
)

_CONFIDENCE_SCALES = ("0..100", "0..1")


class CoordinateSource(StrEnum):
    XML = "xml"
    OCR = "ocr"
    TESSERACT_PAGE = "tesseract_page"
    BAND = "band"
    PILL = "pill"
    CONFIG_COORD = "config_coord"


class BoxPrecision(StrEnum):
    GLYPH = "glyph"
    WORD = "word"
    LINE = "line"
    ELEMENT = "element"
    CONFIG = "config"
    TOKEN_UNION_APPROX = "token_union_approx"


class LocateStatus(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    READ_ERROR = "read_error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
@serializable
class RecipeSpec:
    """一份识别配方的规范描述；content_hash 参与缓存键（契约 §7）。"""

    recipe_id: str
    version: str
    roi: Rect | None = None
    params: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        require_str(self.recipe_id, "RecipeSpec.recipe_id")
        require_str(self.version, "RecipeSpec.version")
        if self.roi is not None and not isinstance(self.roi, Rect):
            raise InvalidDomain("RecipeSpec.roi 必须是 Rect 或 None")
        require_no_duplicates(self.params, "RecipeSpec.params")

    def content_hash(self) -> str:
        canonical = json.dumps(
            {
                "recipe_id": self.recipe_id,
                "version": self.version,
                "roi": None if self.roi is None else [self.roi.x, self.roi.y, self.roi.w, self.roi.h],
                # params 按键排序，键序不同、内容相同算同一配方
                "params": sorted([list(p) for p in self.params]),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def from_jsonable(cls, data: dict) -> "RecipeSpec":
        fields = strict_fields(cls, data)
        if fields["roi"] is not None:
            fields["roi"] = Rect.from_jsonable(fields["roi"])
        fields["params"] = tuple(tuple(p) for p in fields["params"])
        return cls(**fields)


@dataclass(frozen=True, slots=True)
@serializable
class TextToken:
    """识别出的一个文本单元；框精度必须如实标注（契约 §3.4）。"""

    raw_text: str
    normalized_text: str
    box: Rect
    box_precision: BoxPrecision
    reading_ref: str
    confidence_raw: float | None = None
    confidence_scale: str | None = None

    def __post_init__(self) -> None:
        require_str(self.raw_text, "TextToken.raw_text")
        require_opt_str(self.normalized_text, "TextToken.normalized_text")  # 空串允许（纯符号 token）
        if not isinstance(self.box, Rect):
            raise InvalidDomain("TextToken.box 必须是 Rect")
        require_enum(self.box_precision, "TextToken.box_precision", BoxPrecision)
        if self.box_precision is BoxPrecision.CONFIG:
            raise InvalidDomain("TextToken 不允许 config 精度（那是 COORD 候选的标注）")
        require_str(self.reading_ref, "TextToken.reading_ref")
        if (self.confidence_raw is None) != (self.confidence_scale is None):
            raise InvalidDomain("TextToken.confidence_raw 与 confidence_scale 必须成对出现")
        if self.confidence_scale is not None and self.confidence_scale not in _CONFIDENCE_SCALES:
            raise InvalidDomain(f"TextToken.confidence_scale 必须在 {_CONFIDENCE_SCALES}")
        if self.confidence_raw is not None and not isinstance(self.confidence_raw, (int, float)):
            raise InvalidDomain("TextToken.confidence_raw 必须是数值")

    @classmethod
    def from_jsonable(cls, data: dict) -> "TextToken":
        fields = strict_fields(cls, data)
        fields["box"] = Rect.from_jsonable(fields["box"])
        fields["box_precision"] = BoxPrecision(fields["box_precision"])
        return cls(**fields)


@dataclass(frozen=True, slots=True)
@serializable
class Candidate:
    """一个可评分的定位候选；来源规则见模块 docstring（契约 §3.4）。"""

    candidate_id: str
    capture_id: str
    state_epoch: int
    key: str
    source: CoordinateSource
    overlap: int
    rank_in_pass: int
    matched_text: str | None = None
    tap_point: tuple[int, int] | None = None
    box: Rect | None = None
    box_precision: BoxPrecision | None = None
    engine_id: str | None = None
    engine_version: str | None = None
    model_hash: str | None = None
    reading_ref: str | None = None
    rejection_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_str(self.candidate_id, "Candidate.candidate_id")
        require_str(self.capture_id, "Candidate.capture_id")
        require_int(self.state_epoch, "Candidate.state_epoch", minimum=0)
        require_str(self.key, "Candidate.key")
        require_enum(self.source, "Candidate.source", CoordinateSource)
        require_int(self.overlap, "Candidate.overlap", minimum=0)
        require_int(self.rank_in_pass, "Candidate.rank_in_pass", minimum=0)
        for reason in self.rejection_reasons:
            require_str(reason, "Candidate.rejection_reasons")
        if self.tap_point is not None:
            if (
                not isinstance(self.tap_point, tuple)
                or len(self.tap_point) != 2
                or any(type(v) is not int or v < 0 for v in self.tap_point)
            ):
                raise InvalidDomain("Candidate.tap_point 必须是 (x, y) 非负整数对")
        if (self.box is None) != (self.box_precision is None):
            raise InvalidDomain("Candidate.box 与 box_precision 必须成对出现")
        recognized_source = self.source not in (CoordinateSource.XML, CoordinateSource.CONFIG_COORD)
        if recognized_source:
            require_str(self.engine_id, "Candidate.engine_id（识别来源必带）")
            require_str(self.reading_ref, "Candidate.reading_ref（识别来源必带）")
        else:
            if self.engine_id is not None or self.reading_ref is not None:
                raise InvalidDomain(f"{self.source} 候选不得带 engine_id/reading_ref")
        if self.source is CoordinateSource.CONFIG_COORD:
            if self.tap_point is None:
                raise InvalidDomain("CONFIG_COORD 候选必须带 tap_point")
            if self.matched_text is not None:
                raise InvalidDomain("CONFIG_COORD 候选没有识别文本（不能当 text_present 证据）")
        if self.source is CoordinateSource.XML and (
            self.box_precision is None or self.box_precision is not BoxPrecision.ELEMENT
        ):
            raise InvalidDomain("XML 候选的框精度必须是 element")
        if self.engine_version is not None:
            require_str(self.engine_version, "Candidate.engine_version")
        if self.model_hash is not None:
            require_str(self.model_hash, "Candidate.model_hash")

    @classmethod
    def from_jsonable(cls, data: dict) -> "Candidate":
        fields = strict_fields(cls, data)
        fields["source"] = CoordinateSource(fields["source"])
        if fields["box"] is not None:
            fields["box"] = Rect.from_jsonable(fields["box"])
        if fields["box_precision"] is not None:
            fields["box_precision"] = BoxPrecision(fields["box_precision"])
        if fields["tap_point"] is not None:
            fields["tap_point"] = tuple(fields["tap_point"])
        fields["rejection_reasons"] = tuple(fields["rejection_reasons"])
        return cls(**fields)


@dataclass(frozen=True, slots=True)
@serializable
class LocateResult:
    """一次定位的结果；MATCH 的 winner 必须在 ordered 里（契约 §3.4）。"""

    status: LocateStatus
    capture_id: str
    key: str
    duration_ns: int
    winning: Candidate | None = None
    ordered: tuple[Candidate, ...] = ()
    error_code: str | None = None

    def __post_init__(self) -> None:
        require_enum(self.status, "LocateResult.status", LocateStatus)
        require_str(self.capture_id, "LocateResult.capture_id")
        require_str(self.key, "LocateResult.key")
        require_int(self.duration_ns, "LocateResult.duration_ns", minimum=0)
        if self.status is LocateStatus.MATCH:
            if self.winning is None:
                raise InvalidDomain("LocateResult MATCH 必须带 winning")
            if self.winning not in self.ordered:
                raise InvalidDomain("winning 必须出现在 ordered 候选里")
            if self.error_code is not None:
                raise InvalidDomain("MATCH 不应带 error_code")
        else:
            if self.winning is not None:
                raise InvalidDomain(f"LocateResult {self.status} 不得带 winning")
            if self.status in (LocateStatus.READ_ERROR, LocateStatus.TIMEOUT) and not self.error_code:
                raise InvalidDomain(f"LocateResult {self.status} 必须带 error_code")

    @classmethod
    def from_jsonable(cls, data: dict) -> "LocateResult":
        fields = strict_fields(cls, data)
        fields["status"] = LocateStatus(fields["status"])
        if fields["winning"] is not None:
            fields["winning"] = Candidate.from_jsonable(fields["winning"])
        fields["ordered"] = tuple(Candidate.from_jsonable(c) for c in fields["ordered"])
        return cls(**fields)
