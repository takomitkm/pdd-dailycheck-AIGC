"""动作意图与回执（契约 §5）：一次底层调用、结果三态、UNKNOWN 不重发。

业务动作（TAP/SWIPE/BACK）必须带预期前台包、所需窗口类型与依据候选；
生命周期动作（WAKE/START/STOP/HOME/DISMISS_KEYGUARD）走执行器白名单，
不得携带候选依据或业务坐标。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pddcheck.domain.errors import InvalidDomain
from pddcheck.domain.jsonio import serializable, strict_fields
from pddcheck.domain.readings import WindowKind
from pddcheck.domain.validate import require_enum, require_int, require_opt_str, require_str


class ActionKind(StrEnum):
    TAP = "tap"
    SWIPE = "swipe"
    BACK = "back"
    HOME = "home"
    WAKE = "wake"
    DISMISS_KEYGUARD = "dismiss_keyguard"
    START = "start"
    STOP = "stop"


class ExecutionStatus(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    UNKNOWN_EXECUTION = "unknown_execution"


class TerminalKind(StrEnum):
    NONE = "none"
    DONE = "done"
    EXCHANGE = "exchange"
    PENDING = "pending"


_BUSINESS_KINDS = (ActionKind.TAP, ActionKind.SWIPE, ActionKind.BACK)


@dataclass(frozen=True, slots=True)
@serializable
class ActionIntent:
    action_id: str
    run_id: str
    kind: ActionKind
    source_capture_id: str
    state_epoch: int
    geometry_revision: int
    deadline_ns: int
    reason: str
    source_candidate_id: str | None = None
    target_key: str | None = None
    expected_package: str | None = None
    required_window_kind: WindowKind | None = None
    allow_coord: bool = False

    def __post_init__(self) -> None:
        require_str(self.action_id, "ActionIntent.action_id")
        require_str(self.run_id, "ActionIntent.run_id")
        require_enum(self.kind, "ActionIntent.kind", ActionKind)
        require_str(self.source_capture_id, "ActionIntent.source_capture_id")
        require_int(self.state_epoch, "ActionIntent.state_epoch", minimum=0)
        require_int(self.geometry_revision, "ActionIntent.geometry_revision", minimum=0)
        require_int(self.deadline_ns, "ActionIntent.deadline_ns", minimum=1)
        require_str(self.reason, "ActionIntent.reason")
        require_opt_str(self.source_candidate_id, "ActionIntent.source_candidate_id")
        require_opt_str(self.target_key, "ActionIntent.target_key")
        require_opt_str(self.expected_package, "ActionIntent.expected_package")
        if self.required_window_kind is not None:
            require_enum(self.required_window_kind, "ActionIntent.required_window_kind", WindowKind)
        if self.kind in _BUSINESS_KINDS:
            if not self.expected_package or self.required_window_kind is None or not self.source_candidate_id:
                raise InvalidDomain("业务动作必须带 expected_package / required_window_kind / source_candidate_id")
        elif self.source_candidate_id is not None:
            raise InvalidDomain("生命周期动作不携带候选依据")
        if self.allow_coord and self.kind not in (ActionKind.TAP, ActionKind.SWIPE):
            raise InvalidDomain("allow_coord 只对 TAP/SWIPE 有意义")

    @classmethod
    def from_jsonable(cls, data: dict) -> "ActionIntent":
        fields = strict_fields(cls, data)
        fields["kind"] = ActionKind(fields["kind"])
        if fields["required_window_kind"] is not None:
            fields["required_window_kind"] = WindowKind(fields["required_window_kind"])
        return cls(**fields)


@dataclass(frozen=True, slots=True)
@serializable
class ActionReceipt:
    """底层调用结果。ACKNOWLEDGED 是传输确认，不等于业务成功（契约 §5.6）。"""

    action_id: str
    status: ExecutionStatus
    started_ns: int
    ended_ns: int
    error_code: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        require_str(self.action_id, "ActionReceipt.action_id")
        require_enum(self.status, "ActionReceipt.status", ExecutionStatus)
        require_int(self.started_ns, "ActionReceipt.started_ns", minimum=1)
        require_int(self.ended_ns, "ActionReceipt.ended_ns", minimum=1)
        if self.ended_ns < self.started_ns:
            raise InvalidDomain("ActionReceipt.ended_ns 不得早于 started_ns")
        require_opt_str(self.error_code, "ActionReceipt.error_code")
        require_opt_str(self.detail, "ActionReceipt.detail")
        if self.status is not ExecutionStatus.ACKNOWLEDGED and not self.error_code:
            raise InvalidDomain(f"ActionReceipt {self.status} 必须带 error_code")

    @classmethod
    def from_jsonable(cls, data: dict) -> "ActionReceipt":
        fields = strict_fields(cls, data)
        fields["status"] = ExecutionStatus(fields["status"])
        return cls(**fields)
