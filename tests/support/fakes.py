"""公共 fake 全集（契约 §4 的测试替身）。

约定：fake 与真实端口遵守同一合同；未知操作必须抛错而不是悄悄成功；
Recording 系列只记录调用供断言，绝不产生副作用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pddcheck.domain import (
    ActionIntent,
    ActionKind,
    ActionReceipt,
    Deadline,
    ExecutionStatus,
)

from tests.support.clock import FakeClock  # re-export 便捷入口

__all__ = ["FakeClock", "FakeDevice", "FakeVision", "MemoryStore", "RecordingNotifier"]


class FakeDevice:
    """DevicePort 测试替身：预设回执脚本，未知意图抛错，绝不执行真实动作。"""

    def __init__(self) -> None:
        self.receipts: list[ActionReceipt] = []
        self.intents: list[ActionIntent] = []
        self._script: dict[str, ExecutionStatus] = {}
        self._clock: FakeClock | None = None

    def script(self, kind: ActionKind, status: ExecutionStatus, error_code: str | None = None) -> None:
        self._script[kind.value] = status
        self._script[f"{kind.value}:error"] = error_code  # type: ignore[assignment]

    def execute_once(self, intent: ActionIntent, deadline: Deadline) -> ActionReceipt:
        if deadline.expired(self._now_ns()):
            raise TimeoutError(f"FakeDevice: {intent.action_id} 在 deadline 之后才到达")
        self.intents.append(intent)
        status = self._script.get(intent.kind.value)
        if status is None:
            raise AssertionError(f"FakeDevice: 没有为 {intent.kind} 编排回执（未知操作必须失败）")
        receipt = ActionReceipt(
            action_id=intent.action_id,
            status=status,
            started_ns=self._now_ns(),
            ended_ns=self._now_ns() + 1,
            error_code=self._script.get(f"{intent.kind.value}:error"),  # type: ignore[arg-type]
        )
        self.receipts.append(receipt)
        return receipt

    def _now_ns(self) -> int:
        return self._clock.now_ns() if self._clock else 1

    def attach_clock(self, clock: FakeClock) -> None:
        self._clock = clock


class FakeVision:
    """VisionPort 测试替身：按 (recipe_id) 返回预置 TextReading，记录请求。"""

    def __init__(self) -> None:
        self.requests: list[tuple] = []
        self.recognized: list[str] = []

    def recognize(self, capture, recipe, deadline):  # noqa: ANN001 - 测试替身，签名随合同冻结
        self.requests.append((capture.capture_id, recipe.recipe_id))
        raise AssertionError("FakeVision: 需要预置结果再调用（不静默返回空）")

    def preset(self, reading) -> None:
        self.recognized.append(reading)


@dataclass
class MemoryStore:
    """StatePort 测试替身：内存版日标记/账本/intent journal。"""

    markers: set[str] = field(default_factory=set)
    ledger: dict[str, str] = field(default_factory=dict)
    intents: list[ActionIntent] = field(default_factory=list)

    def marker_exists(self, business_date: str) -> bool:
        return business_date in self.markers

    def record_intent(self, intent: ActionIntent) -> None:
        self.intents.append(intent)


class RecordingNotifier:
    """NotificationPort 测试替身：记录 attempt，不发任何网络请求。"""

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def send_once(self, request) -> str:  # noqa: ANN001
        self.attempts.append(request.title)
        return "acknowledged"
