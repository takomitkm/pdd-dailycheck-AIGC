"""设备端口协议（T06）：业务层只依赖这些方法签名。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pddcheck.domain import ActionIntent, ActionReceipt, Capture, FocusState


@runtime_checkable
class ObservationPort(Protocol):
    """只读观测——采集/层级/焦点各自独立时间戳，失败不拿旧值凑。"""

    def capture(self) -> Capture: ...

    def read_hierarchy(self) -> str:
        """返回 XML 文本（调用方做新鲜度与完整性判定）。"""
        ...

    def focus(self) -> FocusState: ...


@runtime_checkable
class DevicePort(ObservationPort, Protocol):
    """观测 + 动作。动作走单次无隐式重发路径；丢响应 → UNKNOWN_EXECUTION。

    坐标不在 ActionIntent 里（那是候选的依据），由调用方显式传入 point：
    TAP 给 (x,y)；SWIPE 给 (x1,y1,x2,y2)。生命周期动作不需要 point。
    """

    state_epoch: int

    def execute(self, intent: ActionIntent,
                point: tuple[int, ...] | None = None) -> ActionReceipt: ...
