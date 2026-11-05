"""FakeClock 独立模块（fakes.py 与 conftest 共用）。"""

from __future__ import annotations

from pddcheck.domain import Deadline


class FakeClock:
    """可控 monotonic 时钟：测试显式推进，绝不真实 sleep（契约 §8 的计时口径）。"""

    def __init__(self, start_ns: int = 1) -> None:
        if start_ns < 1:
            raise ValueError("monotonic 起点必须 >= 1")
        self._now_ns = start_ns

    def now_ns(self) -> int:
        return self._now_ns

    def advance_ns(self, delta: int) -> None:
        if delta < 0:
            raise ValueError("时间不能倒退")
        self._now_ns += delta

    def deadline(self, limit_ns: int) -> Deadline:
        return Deadline(self._now_ns + limit_ns)
