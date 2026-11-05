"""读取采样：状态化 Sample 与真实焦点（契约 §3.2/§3.3）。

核心规则：空结果（ABSENT）不是错误；解码坏图、OCR 崩溃、超时是
UNAVAILABLE/INVALID/TIMEOUT，必须带 error_code，不得伪装成「没找到」。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from pddcheck.domain.errors import InvalidDomain
from pddcheck.domain.jsonio import serializable, strict_fields
from pddcheck.domain.validate import require_enum, require_int, require_opt_str

T = TypeVar("T")


class ReadStatus(StrEnum):
    OK = "ok"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    TIMEOUT = "timeout"


class WindowKind(StrEnum):
    APP = "app"
    STATUSBAR = "statusbar"
    KEYGUARD = "keyguard"
    FOREIGN = "foreign"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
@serializable
class Sample(Generic[T]):
    """一次带状态的读取；value 仅在 OK 时存在（契约 §3.3 的 Sample[T]）。

    value 仅限 JSON 原生类型（str/int/float/bool）；复杂负载一律用引用
    （工件 id/路径），由 evidence 层解析。
    """

    status: ReadStatus
    value: T | None = None
    error_code: str | None = None
    started_ns: int = 0
    ended_ns: int = 0
    source: str = ""

    def __post_init__(self) -> None:
        require_int(self.started_ns, "Sample.started_ns", minimum=0)
        require_int(self.ended_ns, "Sample.ended_ns", minimum=0)
        if self.ended_ns < self.started_ns:
            raise InvalidDomain("Sample.ended_ns 不得早于 started_ns")
        require_opt_str(self.error_code, "Sample.error_code")
        require_opt_str(self.source, "Sample.source")
        if self.status is ReadStatus.OK:
            if self.value is None:
                raise InvalidDomain("Sample OK 必须带 value")
            if self.error_code is not None:
                raise InvalidDomain("Sample OK 不应带 error_code")
        else:
            if self.value is not None:
                raise InvalidDomain(f"Sample {self.status} 不得带 value")
            if self.status is not ReadStatus.ABSENT and not self.error_code:
                raise InvalidDomain(f"Sample {self.status} 必须带 error_code")

    @classmethod
    def ok(cls, value: T, started_ns: int, ended_ns: int, source: str) -> "Sample[T]":
        return cls(ReadStatus.OK, value=value, started_ns=started_ns, ended_ns=ended_ns, source=source)

    @classmethod
    def absent(cls, started_ns: int, ended_ns: int, source: str) -> "Sample[T]":
        return cls(ReadStatus.ABSENT, started_ns=started_ns, ended_ns=ended_ns, source=source)

    @classmethod
    def failed(
        cls, status: ReadStatus, error_code: str, started_ns: int, ended_ns: int, source: str
    ) -> "Sample[T]":
        return cls(status, error_code=error_code, started_ns=started_ns, ended_ns=ended_ns, source=source)

    @classmethod
    def from_jsonable(cls, data: dict) -> "Sample":
        fields = strict_fields(cls, data)
        fields["status"] = ReadStatus(fields["status"])
        return cls(**fields)


@dataclass(frozen=True, slots=True)
@serializable
class FocusState:
    """真实顶层窗口焦点；resumed_package 只是诊断，不能替代窗口判断（契约 §3.2）。"""

    window_kind: WindowKind
    sampled_ns: int
    focused_package: str | None = None
    focused_activity: str | None = None
    resumed_package: str | None = None
    window_label: str | None = None

    def __post_init__(self) -> None:
        require_enum(self.window_kind, "FocusState.window_kind", WindowKind)
        require_int(self.sampled_ns, "FocusState.sampled_ns", minimum=1)
        require_opt_str(self.focused_package, "FocusState.focused_package")
        require_opt_str(self.focused_activity, "FocusState.focused_activity")
        require_opt_str(self.resumed_package, "FocusState.resumed_package")
        require_opt_str(self.window_label, "FocusState.window_label")
        if self.window_kind is WindowKind.APP and not self.focused_package:
            raise InvalidDomain("window_kind=app 必须带 focused_package")

    def allows_business_action(self, package: str) -> bool:
        """业务点击/滑动/应用内 BACK 的焦点门禁（契约 §5.2；I08）。"""
        return self.window_kind is WindowKind.APP and self.focused_package == package

    @classmethod
    def from_jsonable(cls, data: dict) -> "FocusState":
        fields = strict_fields(cls, data)
        fields["window_kind"] = WindowKind(fields["window_kind"])
        return cls(**fields)
