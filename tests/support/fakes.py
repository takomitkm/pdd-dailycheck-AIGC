"""公共 fake（契约 §4 的测试替身）。约定：fake 与真实端口遵守同一合同，
未知操作必须失败而不是悄悄成功；这里先落确定性时钟，其余随 T02 续轮补齐。"""

from __future__ import annotations

from pddcheck.domain import Deadline


class FakeClock:
    """可控 monotonic 时钟：测试显式推进，绝不真实 sleep（契约 §6 的计时口径）。"""

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
