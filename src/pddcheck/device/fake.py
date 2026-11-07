"""协议夹具（T06）：把线上最难复现的语义在 fake 上钉死。

覆盖：
- 重复 action_id → REJECTED（不重复执行）；
- deadline 已过 → REJECTED（deadline_exceeded，不执行）；
- 失效 epoch（intent.state_epoch != 当前）→ REJECTED（epoch_stale）；
- 丢响应 → UNKNOWN_EXECUTION（绝不自动重发）；
- 服务重启（bump_epoch）→ 旧 epoch 的未执行意图全部作废。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from pddcheck.domain import (
    ActionIntent,
    ActionReceipt,
    Capture,
    ExecutionStatus,
    FocusState,
    WindowKind,
)


@dataclass
class _Failure:
    kind: str                        # lost_response | server_restart | io_error


class FakeDevice:
    """DevicePort 的脚本化实现。"""

    def __init__(self, now_ns=None, *, pkg: str = "com.xunmeng.pinduoduo",
                 tap_size=(720, 1280), activity: str = "HomeActivity") -> None:
        self._now = now_ns or (lambda: 0)
        self.pkg = pkg
        self.tap_width, self.tap_height = tap_size
        self.activity = activity
        self.state_epoch = 0
        self.executed: list[ActionIntent] = []
        self._seen_ids: set[str] = set()
        self._failures: deque[_Failure] = deque()
        self._focus_kind = WindowKind.APP

    # ---- 注入 -------------------------------------------------------
    def inject_failure(self, kind: str) -> None:
        self._failures.append(_Failure(kind))

    def bump_epoch(self) -> int:
        """服务/连接重建：epoch+1，旧 epoch 的动作随之失效。"""
        self.state_epoch += 1
        return self.state_epoch

    def set_focus(self, kind: WindowKind, activity: str | None = None) -> None:
        self._focus_kind = kind
        if activity:
            self.activity = activity

    # ---- 观测 -------------------------------------------------------
    def focus(self) -> FocusState:
        return FocusState(window_kind=self._focus_kind, sampled_ns=self._now(),
                          focused_package=self.pkg,
                          focused_activity=self.activity)

    def read_hierarchy(self) -> str:
        return "<hierarchy><node text='' bounds='[0,0][1,1]'/></hierarchy>"

    def capture(self) -> Capture:
        now = self._now()
        return Capture(
            run_id="fake-run", capture_id=f"cap-{now}", state_epoch=self.state_epoch,
            capture_started_ns=now, capture_finished_ns=now,
            focus_before=self.focus(), focus_after=self.focus(),
            tap_width=self.tap_width, tap_height=self.tap_height,
            rotation=0, screenshot_encoding="png", capture_transport="fake",
            screenshot_width=self.tap_width, screenshot_height=self.tap_height,
        )

    # ---- 动作 -------------------------------------------------------
    def execute(self, intent: ActionIntent,
                point: tuple[int, ...] | None = None) -> ActionReceipt:
        now = self._now()
        # 重复 id：拒绝，不重复执行（幂等边界）
        if intent.action_id in self._seen_ids:
            return self._reject(intent, now, "duplicate_action_id")
        # 失效 epoch：拒绝
        if intent.state_epoch != self.state_epoch:
            return self._reject(intent, now, "epoch_stale")
        # deadline 已过：拒绝，不执行
        if now > intent.deadline_ns:
            return self._reject(intent, now, "deadline_exceeded")
        # 故障注入
        if self._failures:
            f = self._failures.popleft()
            if f.kind == "server_restart":
                self.bump_epoch()               # 服务重启 → epoch 变，动作未执行
                return ActionReceipt(action_id=intent.action_id,
                                     status=ExecutionStatus.UNKNOWN_EXECUTION,
                                     started_ns=now, ended_ns=now,
                                     error_code="server_restart")
            if f.kind == "lost_response":
                self._seen_ids.add(intent.action_id)   # 动作已执行，但响应丢失
                self.executed.append(intent)
                return ActionReceipt(action_id=intent.action_id,
                                     status=ExecutionStatus.UNKNOWN_EXECUTION,
                                     started_ns=now, ended_ns=now,
                                     error_code="lost_response")
            # io_error：明确未执行
            return ActionReceipt(action_id=intent.action_id,
                                 status=ExecutionStatus.REJECTED,
                                 started_ns=now, ended_ns=now, error_code="io_error")
        self._seen_ids.add(intent.action_id)
        self.executed.append(intent)
        return ActionReceipt(action_id=intent.action_id,
                             status=ExecutionStatus.ACKNOWLEDGED,
                             started_ns=now, ended_ns=now)

    def _reject(self, intent: ActionIntent, now: int, code: str) -> ActionReceipt:
        return ActionReceipt(action_id=intent.action_id, status=ExecutionStatus.REJECTED,
                             started_ns=now, ended_ns=now, error_code=code)
