"""run 编排（T14 2/2）：把判定核与端口装配成一条可测的端到端管线。

顺序固定（契约/acceptance）：
  预检→锁→读日标记（--force 只跳标记）→读屏事实→点前终态→点亮→核实→
  终态效果（marker/ledger/close）→通知→（证据由调用方落）

设计：所有副作用都从构造期注入，没有任何全局/环境读取；因此可用 FakeClock/
FakeDevice/FakeScreen 在毫秒内跑完整管线。业务失败绝不因通知失败而改写（I11）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pddcheck.cli.exits import ExitCode
from pddcheck.domain import ActionKind, ActionIntent, ExecutionStatus, WindowKind
from pddcheck.notify import NotificationSender, NotifyInput, render_notification
from pddcheck.storage import DailyStore, Journal, LockBusy
from pddcheck.workflow.check_before import CheckBeforeKind, check_done_before_decision
from pddcheck.workflow.terminal import ClosePolicy, terminal_plan
from pddcheck.workflow.verify import (
    VerifyObservation,
    VerifyStage,
    verify_light_decision,
)


class ScreenPort(Protocol):
    """读屏事实（生产里 = 采集+OCR+感知的组合；测试里 = 脚本）。"""

    def light_facts(self) -> dict: ...
    def post_tap_observations(self) -> tuple[VerifyObservation, ...]: ...


@dataclass(frozen=True, slots=True)
class RunOutcome:
    exit_code: ExitCode
    lit: int | None
    rc: int
    title: str
    body: str
    delivered: str | None = None
    marker_written: bool = False
    ledger_written: int | None = None
    close_policy: str | None = None
    skipped: str | None = None         # daily_marker / force 等跳过原因
    notes: tuple[str, ...] = field(default=())


@dataclass(slots=True)
class RunDeps:
    device: object                       # DevicePort
    screen: ScreenPort
    store: DailyStore
    journal: Journal | None
    notifier: NotificationSender
    endpoint: str | None
    evidence_dir: str
    business_date: str
    run_id: str
    now_ns: object                        # () -> int
    lease_factory: object | None = None  # () -> RunLease（可空=不取锁）
    force: bool = False
    close_app_on_ok: bool = True
    steps_label: str = "subsidy bag light"


def _exit(rc: int, lit: int | None) -> ExitCode:
    from pddcheck.cli.exits import exit_for_outcome
    return exit_for_outcome(rc=rc, lit=lit)


def run_once(deps: RunDeps) -> RunOutcome:
    notes: list[str] = []

    # 1) 锁（早退：75）
    lease = None
    if deps.lease_factory is not None:
        try:
            lease = deps.lease_factory()
        except LockBusy:
            return RunOutcome(ExitCode.LOCK_BUSY, None, 75, "PDD ⛔ 并发抢锁", "",
                              skipped="lock_busy", notes=("另一个实例持锁",))
    try:
        # 2) 日标记（--force 只跳过它，不跳锁/焦点/人工兑换边界——I10）
        if not deps.force and deps.store.marker_exists(deps.business_date):
            return RunOutcome(ExitCode.OK, None, 0, "PDD 已完成（今日）", "标记已存在",
                              skipped="daily_marker", notes=("日标记已存在，未动作",))
        if deps.force and deps.store.marker_exists(deps.business_date):
            notes.append("--force：跳过日标记，其它边界照旧")

        # 3) 点前终态
        facts = deps.screen.light_facts()
        pre = check_done_before_decision(
            done_text=facts.get("done_text"),
            exchange_text=facts.get("exchange_text"),
            pend_text=facts.get("pend_text"),
            before_count=facts.get("before_count"))
        lit: int | None = None
        rc = 0
        if pre.kind is CheckBeforeKind.DONE:
            lit = 1
        elif pre.kind is CheckBeforeKind.EXCHANGE:
            lit = 2
        elif pre.kind is CheckBeforeKind.PENDING:
            lit = 4                      # pend 是 lit=4，进程码 0（acceptance §5）
        else:
            # 4) 点亮一枪 + 核实
            intent = _make_tap_intent(deps, facts)
            receipt = deps.device.execute(intent, facts.get("tap_point"))
            if deps.journal is not None:
                deps.journal.record_intent(intent.action_id, "tap",
                                           {"target": "light", "state_epoch": deps.device.state_epoch,
                                            "before_count": pre.before_count})
                deps.journal.record_receipt(intent.action_id, receipt.status.value, receipt.error_code)
            if receipt.status is ExecutionStatus.UNKNOWN_EXECUTION:
                # 未知执行：绝不自动重发；按无法核实处理（I15）
                notes.append(f"动作执行状态未知（{receipt.error_code}），不重发按无法核实")
                rc, lit = 1, None
            else:
                obs = deps.screen.post_tap_observations()
                decision = verify_light_decision(pre.before_count, facts.get("tap_method", "ocr"), obs)
                rc, lit = decision.rc, decision.lit
                notes.append(f"核实：{decision.proof_kind.value} — {decision.why}")

        # 内部 verify 的 rc=1（未过）对用户是 6（LIGHT_NOT_APPLIED）——acceptance §5
        business_rc = 6 if rc == 1 else rc

        # 5) 终态效果
        plan = terminal_plan(rc=business_rc, lit=lit, done_word=pre.done_word,
                             pend_days=facts.get("pend_days"),
                             ledger_current=deps.store.ledger_read(),
                             close_app_on_ok=deps.close_app_on_ok)
        marker_written = False
        ledger_written = None
        if plan.marker_write:
            deps.store.write_marker(deps.business_date)
            marker_written = True
        if plan.ledger_write is not None:
            deps.store.ledger_write(plan.ledger_write)
            ledger_written = plan.ledger_write

        # 6) 通知（失败不改业务 rc——I11）
        title, body = render_notification(NotifyInput(
            rc=business_rc, lit=lit, evidence_dir=deps.evidence_dir,
            steps=deps.steps_label, done_word=pre.done_word,
            pend_days=facts.get("pend_days"),
            pend_line=facts.get("pend_line"),
            pend_msg="", exc_msg="", verify_why=""))
        delivery = deps.notifier.send(deps.endpoint, title, body)

        return RunOutcome(_exit(business_rc, lit), lit, business_rc, title, body,
                          delivered=delivery.status.value,
                          marker_written=marker_written,
                          ledger_written=ledger_written,
                          close_policy=str(plan.close_policy),
                          notes=tuple(notes))
    finally:
        if lease is not None:
            lease.release()


def _make_tap_intent(deps: RunDeps, facts: dict) -> ActionIntent:
    return ActionIntent(
        action_id=f"{deps.run_id}-light-{deps.now_ns()}",
        run_id=deps.run_id,
        kind=ActionKind.TAP,
        source_capture_id=facts.get("capture_id", "cap"),
        state_epoch=getattr(deps.device, "state_epoch", 0),
        geometry_revision=facts.get("geometry_revision", 0),
        deadline_ns=deps.now_ns() + 15_000_000_000,
        reason="点亮",
        source_candidate_id="light-cand",
        target_key="light",
        expected_package="com.xunmeng.pinduoduo",
        required_window_kind=WindowKind.APP,
        allow_coord=facts.get("tap_method") == "coord",
    )
