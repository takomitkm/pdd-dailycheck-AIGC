"""单调时钟与截止时间（契约 §8）。

Deadline 保存绝对 monotonic_ns；``child()`` 取 min(父截止, now+limit)，
子函数不得重置父截止。墙钟只用于展示与业务日期，不参与预算。
"""

from __future__ import annotations

from dataclasses import dataclass

from pddcheck.domain.errors import InvalidDomain
from pddcheck.domain.jsonio import serializable, strict_fields
from pddcheck.domain.validate import require_int


@dataclass(frozen=True, slots=True)
@serializable
class Deadline:
    at_ns: int

    def __post_init__(self) -> None:
        require_int(self.at_ns, "Deadline.at_ns", minimum=1)

    def expired(self, now_ns: int) -> bool:
        return now_ns >= self.at_ns

    def remaining_ns(self, now_ns: int) -> int:
        return self.at_ns - now_ns

    def child(self, limit_ns: int, now_ns: int) -> "Deadline":
        """子预算 = min(父截止, now+limit)；limit<=0 或 now 非法当场拒绝。"""
        require_int(limit_ns, "limit_ns", minimum=1)
        require_int(now_ns, "now_ns", minimum=1)
        return Deadline(min(self.at_ns, now_ns + limit_ns))

    @classmethod
    def from_jsonable(cls, data: dict) -> "Deadline":
        return cls(**strict_fields(cls, data))
