"""domain：纯类型、纯模型与纯函数。

只依赖标准库；禁止 import adbutils/uiautomator2/RapidOCR/Pillow/HTTP/文件系统业务
适配器（契约 §1，依赖边界测试在 tests/contracts）。所有对外对象 frozen，
跨进程 JSON 走 jsonio 的 schema 信封。
"""

from pddcheck.domain.capture import Capture, ComponentStatus
from pddcheck.domain.clock import Deadline
from pddcheck.domain.errors import (
    DomainError,
    InvalidDomain,
    PolicyViolation,
    ReadFailure,
    StaleObservation,
    UnknownExecution,
)
from pddcheck.domain.geometry import Geometry, Rect
from pddcheck.domain.jsonio import envelope, from_envelope, jsonable, serializable
from pddcheck.domain.readings import FocusState, ReadStatus, Sample, WindowKind
from pddcheck.domain.validate import (
    require_int,
    require_no_duplicates,
    require_opt_str,
    require_sha256,
    require_str,
)
from pddcheck.domain.version import SCHEMA_VERSION
from pddcheck.domain.vision import (
    BoxPrecision,
    Candidate,
    CoordinateSource,
    LocateResult,
    LocateStatus,
    RecipeSpec,
    TextToken,
)
from pddcheck.domain.workflow import (
    ActionIntent,
    ActionKind,
    ActionReceipt,
    ExecutionStatus,
    TerminalKind,
)

__all__ = [
    "SCHEMA_VERSION",
    # errors
    "DomainError",
    "InvalidDomain",
    "ReadFailure",
    "StaleObservation",
    "UnknownExecution",
    "PolicyViolation",
    # clock
    "Deadline",
    # geometry
    "Rect",
    "Geometry",
    # readings
    "ReadStatus",
    "WindowKind",
    "Sample",
    "FocusState",
    # capture
    "ComponentStatus",
    "Capture",
    # vision
    "CoordinateSource",
    "BoxPrecision",
    "LocateStatus",
    "RecipeSpec",
    "TextToken",
    "Candidate",
    "LocateResult",
    # workflow
    "ActionKind",
    "ExecutionStatus",
    "TerminalKind",
    "ActionIntent",
    "ActionReceipt",
    # jsonio
    "jsonable",
    "envelope",
    "from_envelope",
    "serializable",
    # validate
    "require_int",
    "require_str",
    "require_opt_str",
    "require_sha256",
    "require_no_duplicates",
]
