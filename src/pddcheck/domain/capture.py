"""Capture：一次有界观察的不可变记录（契约 §3.3）。

XML、截图、焦点不是原子同时获得：各自带采样时间与状态；跨度超限或
epoch 变化必须重开 Observation，不得篡改旧对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pddcheck.domain.errors import InvalidDomain
from pddcheck.domain.jsonio import serializable, strict_fields
from pddcheck.domain.readings import FocusState
from pddcheck.domain.validate import (
    require_enum,
    require_int,
    require_no_duplicates,
    require_opt_str,
    require_sha256,
    require_str,
)

_ROTATIONS = (0, 90, 180, 270)


class ComponentStatus(StrEnum):
    """capture 各组成部件的采集状态；COHERENCE_UNCERTAIN 表示部件间时差超限。"""

    OK = "ok"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    TIMEOUT = "timeout"
    COHERENCE_UNCERTAIN = "coherence_uncertain"


@dataclass(frozen=True, slots=True)
@serializable
class Capture:
    run_id: str
    capture_id: str
    state_epoch: int
    capture_started_ns: int
    capture_finished_ns: int
    focus_before: FocusState
    focus_after: FocusState
    tap_width: int
    tap_height: int
    rotation: int
    screenshot_encoding: str
    capture_transport: str
    display_id: int | None = None
    png_ref: str | None = None
    png_sha256: str | None = None
    pixel_sha256: str | None = None
    screenshot_width: int | None = None
    screenshot_height: int | None = None
    xml_ref: str | None = None
    xml_sha256: str | None = None
    xml_sampled_ns: int | None = None
    component_statuses: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        require_str(self.run_id, "Capture.run_id")
        require_str(self.capture_id, "Capture.capture_id")
        require_int(self.state_epoch, "Capture.state_epoch", minimum=0)
        require_int(self.capture_started_ns, "Capture.capture_started_ns", minimum=1)
        require_int(self.capture_finished_ns, "Capture.capture_finished_ns", minimum=1)
        if self.capture_finished_ns < self.capture_started_ns:
            raise InvalidDomain("Capture.capture_finished_ns 不得早于 capture_started_ns")
        if not isinstance(self.focus_before, FocusState) or not isinstance(self.focus_after, FocusState):
            raise InvalidDomain("Capture.focus_before/after 必须是 FocusState")
        require_int(self.tap_width, "Capture.tap_width", minimum=1)
        require_int(self.tap_height, "Capture.tap_height", minimum=1)
        if self.rotation not in _ROTATIONS:
            raise InvalidDomain(f"Capture.rotation 必须在 {_ROTATIONS}，得到 {self.rotation}")
        require_str(self.screenshot_encoding, "Capture.screenshot_encoding")
        require_str(self.capture_transport, "Capture.capture_transport")
        if self.display_id is not None:
            require_int(self.display_id, "Capture.display_id", minimum=0)
        # ref 与 sha 成对出现：只留路径不留指纹（或反之）都算坏证据。
        if (self.png_ref is None) != (self.png_sha256 is None):
            raise InvalidDomain("Capture.png_ref 与 png_sha256 必须成对出现")
        if (self.xml_ref is None) != (self.xml_sha256 is None):
            raise InvalidDomain("Capture.xml_ref 与 xml_sha256 必须成对出现")
        if self.png_sha256 is not None:
            require_sha256(self.png_sha256, "Capture.png_sha256")
            require_str(self.png_ref, "Capture.png_ref")
        if self.xml_sha256 is not None:
            require_sha256(self.xml_sha256, "Capture.xml_sha256")
            require_str(self.xml_ref, "Capture.xml_ref")
        if self.xml_sampled_ns is not None:
            require_int(self.xml_sampled_ns, "Capture.xml_sampled_ns", minimum=1)
        if self.pixel_sha256 is not None:
            require_sha256(self.pixel_sha256, "Capture.pixel_sha256")
        if self.screenshot_width is not None:
            require_int(self.screenshot_width, "Capture.screenshot_width", minimum=1)
        if self.screenshot_height is not None:
            require_int(self.screenshot_height, "Capture.screenshot_height", minimum=1)
        for key, status in self.component_statuses:
            if not key:
                raise InvalidDomain("Capture.component_statuses 的键必须非空")
            require_enum(status, f"Capture.component_statuses[{key}]", ComponentStatus)
        require_no_duplicates(self.component_statuses, "Capture.component_statuses")

    @property
    def duration_ns(self) -> int:
        return self.capture_finished_ns - self.capture_started_ns

    @classmethod
    def from_jsonable(cls, data: dict) -> "Capture":
        fields = strict_fields(cls, data)
        fields["focus_before"] = FocusState.from_jsonable(fields["focus_before"])
        fields["focus_after"] = FocusState.from_jsonable(fields["focus_after"])
        fields["component_statuses"] = tuple(
            (str(key), ComponentStatus(status)) for key, status in fields["component_statuses"]
        )
        return cls(**fields)
