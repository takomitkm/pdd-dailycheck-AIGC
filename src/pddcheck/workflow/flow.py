"""run 编排（T14 2/2）：把判定核与端口装配成一条可测的端到端管线。

顺序固定（契约/acceptance）：
  预检→锁→读日标记（--force 只跳标记）→读屏事实→点前终态→点亮→核实→
  终态效果（marker/ledger/close）→通知→（证据由调用方落）

设计：所有副作用都从构造期注入，没有任何全局/环境读取；因此可用 FakeClock/
FakeDevice/FakeScreen 在毫秒内跑完整管线。业务失败绝不因通知失败而改写（I11）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from pddcheck.exits import ExitCode, exit_for_outcome
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
    # 流程段（就绪/入口/福袋）失败时由调用方带进来的 rc（4/5/7）：
    # 一旦非空，run_once 直接按该 rc 收尾，不再执行点亮段（真机教训：
    # 阶段失败后继续跑点亮会拿错页的事实做弱证明 → 误报 lit3）。
    stage_failure_rc: int | None = None
    stage_failure_why: str | None = None
    # 纯观察（--dry-run）：识别与决策照做，但**不执行任何业务动作、不写标记/账本、不推送**。
    # 用途：并行观察期只取证，确认新流程的判断与旧流程一致，而不代替签到。
    dry_run: bool = False
    # 点亮后的浏览任务段（生产 11-08 实测必需：点「立即点亮」后是「滑动浏览10秒」页）。
    # 默认 False：47 案行为基线不包含浏览段；CLI 真机路径显式开启。
    browse_after_light: bool = False
    browse_sleep: object | None = None   # 注入 sleep（测试用）；默认 time.sleep


def _exit(rc: int, lit: int | None) -> ExitCode:
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

        # 3) 点前终态（含就绪/入口/福袋段；阶段失败→rc4/5 直接收尾）
        from pddcheck.workflow.stages import StageFailure
        stage_rc: int | None = getattr(deps, "stage_failure_rc", None)
        facts: dict = {}
        pre = None
        if stage_rc is not None:
            notes.append(f"阶段失败 rc={stage_rc}：{getattr(deps, 'stage_failure_why', '')}")
        else:
            try:
                facts = deps.screen.light_facts()
            except StageFailure as exc:
                stage_rc = exc.rc
                notes.append(f"阶段失败 rc={exc.rc}：{exc.why}")

        lit: int | None = None
        rc = 0
        if stage_rc is None:
            pre = check_done_before_decision(
                done_text=facts.get("done_text"),
                exchange_text=facts.get("exchange_text"),
                pend_text=facts.get("pend_text"),
                before_count=facts.get("before_count"))
            if pre.kind is CheckBeforeKind.DONE:
                lit = 1
            elif pre.kind is CheckBeforeKind.EXCHANGE:
                lit = 2
            elif pre.kind is CheckBeforeKind.PENDING:
                lit = 4                  # pend 是 lit=4，进程码 0（acceptance §5）
            elif deps.dry_run:
                # 纯观察：本来会点这一枪，但**不点**（也不核实、不写标记）。
                lit = 0
                notes.append(f"dry-run：本来会点 {pre.before_count} 那一枪"
                             f"（method={pre.kind.value}），本次不执行")
            elif facts.get("browse_page"):
                # 生产 11-08 晚实测：点完「立即点亮」落在**浏览页**（「滑动浏览当前
                # 页面10秒即可点亮」）——此时没有「立即点亮」按钮，正确动作是直接
                # 做浏览段（滑满 10s），再核实。
                if deps.dry_run:
                    notes.append("dry-run：当前已是浏览页，本来会滑满 10s，本次不滑")
                    lit = 0
                else:
                    swipe_ok = _browse_after_light(deps, notes)
                    obs = deps.screen.post_tap_observations()
                    decision = verify_light_decision(pre.before_count, facts.get("tap_method", "ocr"), obs)
                    rc, lit = decision.rc, decision.lit
                    notes.append(f"核实：{decision.proof_kind.value} — {decision.why}"
                                 + ("（浏览页直滑）" if swipe_ok else ""))
            elif facts.get("tap_point") is None:
                # 生产 11-08 补签踩到：整页读不到「立即点亮」→ tap_point=None，
                # 旧弱证明把「没点」报成 lit3 并写标记。废除：无点不点，rc6 不写标记。
                notes.append("点亮失败：定位不到「立即点亮」（整页+裁片都没有）→ rc6，不写标记")
                rc, lit = 6, None
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
                    notes.append(f"动作执行状态未知（{receipt.error_code}），不重发按无法核实")
                    rc, lit = 1, None
                else:
                    # 4.5) 点亮后的**浏览任务段**（生产 11-08 晚实测：点「立即点亮」
                    # 后跳到浏览页「滑动浏览当前页面10秒即可点亮」——必须滚动才算点亮。
                    # 旧脚本 I06 同款：最终 20 次下滑）。做完再核实。
                    swipe_ok = False
                    if getattr(deps, "browse_after_light", False):
                        swipe_ok = _browse_after_light(deps, notes)
                    obs = deps.screen.post_tap_observations()
                    decision = verify_light_decision(pre.before_count, facts.get("tap_method", "ocr"), obs)
                    rc, lit = decision.rc, decision.lit
                    notes.append(f"核实：{decision.proof_kind.value} — {decision.why}"
                                 + ("（浏览段已执行）" if swipe_ok else ""))

        # 内部 verify 的 rc=1（未过）对用户是 6（LIGHT_NOT_APPLIED）——acceptance §5
        business_rc = stage_rc if stage_rc is not None else (6 if rc == 1 else rc)
        done_word = pre.done_word if pre is not None else None

        # 5) 终态效果
        plan = terminal_plan(rc=business_rc, lit=lit, done_word=done_word,
                             pend_days=facts.get("pend_days"),
                             ledger_current=deps.store.ledger_read(),
                             close_app_on_ok=deps.close_app_on_ok)
        marker_written = False
        ledger_written = None
        operational_failed = False
        if deps.dry_run:
            # 纯观察：不写标记、不写账本（否则会把今天标成「已签到」而实际没点）
            notes.append("dry-run：跳过标记/账本写入与推送（只留证据）")
        else:
            try:
                if plan.marker_write:
                    deps.store.write_marker(deps.business_date)
                    marker_written = True
                if plan.ledger_write is not None:
                    ok = deps.store.ledger_write(plan.ledger_write)
                    if not ok:
                        raise OSError("账本写入失败")
                    ledger_written = plan.ledger_write
            except OSError as exc:
                # D04：业务成功但状态落盘失败 → 进程码 73，业务 rc 另存，绝不虚称已写
                operational_failed = True
                notes.append(f"状态写入失败（operational）：{exc}")

        # 6) 通知（失败不改业务 rc——I11）
        title, body = render_notification(NotifyInput(
            rc=business_rc, lit=lit, evidence_dir=deps.evidence_dir,
            steps=deps.steps_label, done_word=done_word,
            pend_days=facts.get("pend_days"),
            pend_line=facts.get("pend_line"),
            pend_msg="", exc_msg="", verify_why=""))
        if deps.dry_run:
            from pddcheck.notify import DeliveryResult, DeliveryStatus
            delivery = DeliveryResult(DeliveryStatus.SKIPPED, 0, None, "dry-run")
        else:
            delivery = deps.notifier.send(deps.endpoint, title, body)

        if operational_failed:
            return RunOutcome(ExitCode.STATE_DIR_FAILED, lit, business_rc, title, body,
                              delivered=delivery.status.value,
                              marker_written=False, ledger_written=None,
                              close_policy=str(plan.close_policy),
                              notes=tuple(notes) + ("business_rc=" + str(business_rc),))
        return RunOutcome(_exit(business_rc, lit), lit, business_rc, title, body,
                          delivered=delivery.status.value,
                          marker_written=marker_written,
                          ledger_written=ledger_written,
                          close_policy=str(plan.close_policy),
                          notes=tuple(notes))
    finally:
        if lease is not None:
            lease.release()


def _browse_after_light(deps: "RunDeps", notes: list) -> bool:
    """点亮后的浏览任务（生产 11-08 实测：点「立即点亮」后进入
    「滑动浏览当前页面10秒即可点亮」页面，必须滚动 10 秒才真正点亮）。

    手势参数照抄旧脚本 browse_page（pdd.sh L1227-1252 / L81-95，10-09/10-10 实测沉淀）：
    - x=0.75×720=540；单次 y1=0.8×1280=1024 → y2=y1-半屏(640)=384（**不超过半屏**，
      滑过头进度卡甩出屏幕）；
    - **按压 800ms**（这才是计入浏览时长的部分；300ms 无效——11-08 实测滑了 20 下没点亮）；
    - 两次之间不留空档（BROWSE_WAIT=0）；
    - 按秒表滑满 15s（BROWSE_SECONDS，给 10s 计时留富余），保险丝 60 下。
    返回是否滑满时长。
    """
    from pddcheck.domain.errors import InvalidDomain
    sleep = getattr(deps, "browse_sleep", None) or time.sleep
    bx, y1, y2 = 540, 1024, 384
    dur_ms = 800
    t0 = time.monotonic()
    ok = 0
    max_swipes = 60
    while time.monotonic() - t0 < 15.0 and ok < max_swipes:
        try:
            intent = ActionIntent(
                action_id=f"{deps.run_id}-browse-{ok}-{deps.now_ns()}",
                run_id=deps.run_id, kind=ActionKind.SWIPE,
                source_capture_id="cap", state_epoch=getattr(deps.device, "state_epoch", 0),
                geometry_revision=0, deadline_ns=deps.now_ns() + 15_000_000_000,
                reason=f"浏览任务滑动 {ok + 1}（x={bx} {y1}->{y2} {dur_ms}ms）",
                source_candidate_id="browse-cand",
                target_key="browse",
                expected_package="com.xunmeng.pinduoduo",
                required_window_kind=WindowKind.APP)
            deps.device.execute(intent, (bx, y1, bx, y2))
            ok += 1
        except InvalidDomain as exc:
            notes.append(f"浏览段第 {ok + 1} 次滑动被拒：{exc}")
            break
    elapsed = round(time.monotonic() - t0, 1)
    notes.append(f"浏览任务段：{ok} 次滑动 / {elapsed}s（目标 ≥10s）")
    return elapsed >= 10.0


def _make_tap_intent(deps: RunDeps, facts: dict) -> ActionIntent:    return ActionIntent(
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
