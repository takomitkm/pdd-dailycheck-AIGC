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

    def post_tap_observations(self, stage: VerifyStage = VerifyStage.AFTER_DIRECT
                              ) -> tuple[VerifyObservation, ...]:
        """核实观察。stage=本次读屏属于 verify 阶梯的哪一级（G1 接线）；
        阶梯关（47 案基线）时调用方不传参，实现按 AFTER_DIRECT 标注。"""
        ...

    def locate_target(self, key: str) -> tuple[int, int] | None:
        """G1/G2/G5：当前帧上定位某目标（bag 胶囊/popup 关闭词），没有则 None。

        语义协议（生产 ScreenPort 必须真实现）：纯观察帧定位，绝不点、绝不盲点
        坐标兜底——认不到字就 None（旧 text_present 口径）。
        测试 Screen 可不实现（getattr 鸭子判断会跳过）。
        """
        ...


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
    # 终态效果执行（G4/G8 迁移审计补上）：final_scroll（I06 最终 20 次下滑）、
    # close_policy 下发（rc0 force-stop+HOME / rc≠0 HOME / lit2/4 不动）、
    # last_activity 采集。默认 False 保持 47 案基线；CLI 真机路径显式开启。
    execute_terminal_effects: bool = False
    # 证据保留天数（G9：旧 KEEP_DAYS=7；None/0=不清理）
    keep_days: int | None = 7
    # G1/G2/G3/G5（迁移审计）：verify 四阶段阶梯真执行——浏览滑完 BACK 回落点核实、
    # 落频道页认到 bag 再点回活动页、清浮层复读、重进福袋页兜底、奖励浮层点「开心收下」。
    # 默认 False（47 案基线只喂 AFTER_DIRECT）；CLI 真机路径显式开启。
    verify_ladder: bool = False


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
            elif facts.get("tap_point") is None:
                # 整页+裁片都定位不到「立即点亮」：两种可能——
                # a) 已在**浏览任务页**（点完立即点亮后；该页横幅 OCR 读不出，
                #    pdd.sh L243 实测「四档全瞎」，不能靠文本判定）；
                # b) 页面被弹窗/其他覆盖。
                # 滑动是**无害动作**（在 pdd 页面内滚动），滑满 10s 后再诚实核实：
                # 点亮了 → lit3；没点亮 → rc6 不写标记（旧弱证明口径已废除）。
                if deps.dry_run:
                    notes.append("dry-run：定位不到「立即点亮」，本来会滑 15s 再核实，本次不滑")
                    lit = 0
                else:
                    notes.append("定位不到「立即点亮」→ 按浏览任务处理（滑 15s 后核实）")
                    swipe_ok = _browse_after_light(deps, notes)
                    obs = _verify_after_light(deps, notes, browsed=True,
                                              verify_ladder=getattr(deps, "verify_ladder", False))
                    decision = verify_light_decision(pre.before_count, facts.get("tap_method", "ocr"), obs)
                    rc, lit = decision.rc, decision.lit
                    notes.append(f"核实：{decision.proof_kind.value} — {decision.why}"
                                 + ("（浏览滑动已执行）" if swipe_ok else ""))
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
                    obs = _verify_after_light(deps, notes, browsed=swipe_ok,
                                              verify_ladder=getattr(deps, "verify_ladder", False))
                    decision = verify_light_decision(pre.before_count, facts.get("tap_method", "ocr"), obs)
                    rc, lit = decision.rc, decision.lit
                    if decision.tap_point is not None and not deps.dry_run:
                        # G3：奖励浮层在场=点着了的凭据，顺手把「开心收下」点掉
                        #（契约 L197：只有奖励浮层证明分支允许 take；判定核给点才许点）
                        _take_prize(deps, decision.tap_point, notes)
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

        # 6) 终态效果执行（生产教训：terminal_plan 早就算出 close/final_scroll，
        #    但执行器只把它当字符串写进 RunOutcome、从不真正下发 → 跑成功既不关 app、
        #    也不做 I06 要求的最终 20 次下滑。这里补上，且严格按旧脚本收尾纪律：
        #    rc0=force-stop+HOME；rc≠0=只 HOME；lit2/4=留在屏前一个键都不放。）
        last_activity = None
        if getattr(deps, "execute_terminal_effects", False) and not deps.dry_run:
            if plan.final_scroll and business_rc == 0:
                _final_scroll(deps, notes)
            # last_activity 必须在关 app 之前读（pdd.sh L1622：按完 HOME 就只剩桌面了）。
            last_activity = _read_last_activity(deps)
            _apply_close_policy(deps, plan, notes)
            # 证据保留（G9：旧 prune_evidence；失败只记 notes，不改业务 rc）
            if getattr(deps, "keep_days", None):
                try:
                    pruned = deps.store.prune_evidence(deps.keep_days)
                    if pruned:
                        notes.append(f"证据清理：删 {pruned} 个过期目录（keep_days={deps.keep_days}）")
                except Exception as exc:
                    notes.append(f"证据清理失败（忽略）：{exc}")

        # 7) 通知（失败不改业务 rc——I11）
        title, body = render_notification(NotifyInput(
            rc=business_rc, lit=lit, evidence_dir=deps.evidence_dir,
            steps=deps.steps_label, done_word=done_word,
            pend_days=facts.get("pend_days"),
            pend_line=facts.get("pend_line"),
            pend_msg="", exc_msg="", verify_why="",
            last_activity=last_activity))
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


def _verify_after_light(deps: RunDeps, notes: list, *, browsed: bool,
                        verify_ladder: bool) -> tuple[VerifyObservation, ...]:
    """点亮后的核实观察收集。

    - verify_ladder=False（47 案基线）：照旧单次 post_tap_observations；
    - verify_ladder=True（G1/G2/G5 迁移）：跑旧 verify_light 的阶梯——
      1. browsed 时先 BACK 离开浏览/消费券页，落点读进度（AFTER_BACK）；
      2. 进度读不到且认到「抽福袋」胶囊 → 点它回活动页再读（AFTER_REENTER）；
      3. 仍读不到 → 清浮层（认到关闭词才点）再读（AFTER_POPUP）。
    未接线：AFTER_REENTER_BAG（重进福袋页兜底）要跨 StageRunner 层，本版不跑；
    不跑这条救场路的失败形态仍是 rc6（旧脚本这条路线失败也是 rc6）——
    只少一条救场路，不会多一次误报成功。每步动作失败只记 notes，
    观察交给 verify_light_decision 按旧阶梯判。
    """
    if not verify_ladder:
        return deps.screen.post_tap_observations()

    obs: list[VerifyObservation] = []
    if browsed:
        # G2：BACK 离开浏览页（旧 L1316-1319「滑完必按 BACK」）
        _stage_back(deps, notes, "浏览完，按 BACK 离开消费券页")
        obs.extend(deps.screen.post_tap_observations(VerifyStage.AFTER_BACK))
        if _obs_count(obs) is None:
            # 落频道页且认到「抽福袋」胶囊 → 点回活动页（旧 L1322-1327）
            bag_point = _locate_on_screen(deps, notes, "bag")
            if bag_point is not None:
                _tap_point(deps, bag_point, "BACK 落在频道页，点「抽福袋」胶囊回活动页", notes)
                obs.extend(deps.screen.post_tap_observations(VerifyStage.AFTER_REENTER))
    else:
        obs.extend(deps.screen.post_tap_observations())          # AFTER_DIRECT

    if _obs_count(obs) is None:
        # G5：进度行读不到，可能是浮层盖着——清浮层（认到关闭词才点）再读（旧 L1353-1358）
        popup_point = _locate_on_screen(deps, notes, "popup")
        if popup_point is not None:
            _tap_point(deps, popup_point, "进度行读不到，先点掉浮层再读", notes)
        obs.extend(deps.screen.post_tap_observations(VerifyStage.AFTER_POPUP))
    return tuple(obs)


def _obs_count(obs: tuple[VerifyObservation, ...]) -> int | None:
    """已收观察里是否已有进度数字（任一阶段）；没有则 None。"""
    for o in obs:
        if o.after_count is not None:
            return o.after_count
    return None


def _locate_on_screen(deps: RunDeps, notes: list, key: str) -> tuple[int, int] | None:
    """给 verify 阶梯用：当前帧上认某目标（bag 胶囊 / popup 关闭词）。

    ScreenPort 可实现 locate_target(key)->(x,y)|None；没实现就跳过这一路
    （绝不盲点——10-11 的 rc=5 就是盲点坐标惹的）。
    """
    locate = getattr(deps.screen, "locate_target", None)
    if locate is None:
        return None
    try:
        return locate(key)
    except Exception as exc:
        notes.append(f"落点认 {key} 失败（跳过这一路）：{exc}")
        return None


def _stage_back(deps: RunDeps, notes: list, reason: str) -> None:
    try:
        intent = ActionIntent(
            action_id=f"{deps.run_id}-back-{deps.now_ns()}",
            run_id=deps.run_id, kind=ActionKind.BACK,
            source_capture_id="verify", state_epoch=getattr(deps.device, "state_epoch", 0),
            geometry_revision=0, deadline_ns=deps.now_ns() + 15_000_000_000,
            reason=reason, source_candidate_id="verify-back", target_key="verify",
            expected_package="com.xunmeng.pinduoduo", required_window_kind=WindowKind.APP)
        deps.device.execute(intent, None)
    except Exception as exc:
        notes.append(f"BACK 被拒（继续核实）：{exc}")


def _tap_point(deps: RunDeps, point: tuple[int, int], reason: str, notes: list) -> None:
    try:
        intent = ActionIntent(
            action_id=f"{deps.run_id}-tap-{deps.now_ns()}",
            run_id=deps.run_id, kind=ActionKind.TAP,
            source_capture_id="verify", state_epoch=getattr(deps.device, "state_epoch", 0),
            geometry_revision=0, deadline_ns=deps.now_ns() + 15_000_000_000,
            reason=reason, source_candidate_id="verify-tap", target_key="verify",
            expected_package="com.xunmeng.pinduoduo", required_window_kind=WindowKind.APP)
        receipt = deps.device.execute(intent, point)
        # 成功/拒绝都留痕（真机查因需要「这一枪到底打没打成」）
        notes.append(f"{reason}（{point}，{receipt.status.value}）")
    except Exception as exc:
        notes.append(f"点 {point} 被拒（继续核实）：{exc}")


def _take_prize(deps: RunDeps, point: tuple[int, int], notes: list) -> None:
    """G3：奖励浮层在场 + 判定核给了 take 点 → 点「开心收下」收奖（旧 take_prize_overlay）。"""
    _tap_point(deps, point, "奖励浮层在场，点「开心收下」收下", notes)


def _browse_after_light(deps: "RunDeps", notes: list) -> bool:
    """点亮后的浏览任务（生产 11-08 实测：点「立即点亮」后进入
    「滑动浏览当前页面10秒即可点亮」页面，必须滚动 10 秒才真正点亮）。

    手势按**屏幕比例**现算（用户口径 2026-11-08：不写死像素，跟随真实 tap 空间），
    数值来自旧脚本 browse_page 的比例口径（pdd.sh L1227-1252 / L81-95）：
    - x = 0.75 × tap_w（720 宽上是 540）；
    - 单次 y1 = 0.8 × tap_h → y2 = y1 − 半屏（不超过半屏，滑过头进度卡甩出屏幕）；
    - **按压 800ms**（这才是计入浏览时长的部分；300ms 无效——11-08 实测）；
    - 两次之间不留空档；按秒表滑满 15s（给 10s 计时留富余），保险丝 60 下。
    返回是否滑满时长。
    """
    from pddcheck.domain.errors import InvalidDomain
    sleep = getattr(deps, "browse_sleep", None) or time.sleep
    tw = int(getattr(deps.device, "tap_width", 0) or 720)
    th = int(getattr(deps.device, "tap_height", 0) or 1280)
    if tw <= 0 or th <= 0:
        tw, th = 720, 1280
    bx = int(tw * 0.75)
    y1 = int(th * 0.8)
    y2 = max(2, y1 - th // 2)          # 单次不超过半屏
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
                reason=f"浏览任务滑动 {ok + 1}（比例 x=0.75 y=0.8→0.3 {dur_ms}ms）",
                source_candidate_id="browse-cand",
                target_key="browse",
                expected_package="com.xunmeng.pinduoduo",
                required_window_kind=WindowKind.APP)
            deps.device.execute(intent, (bx, y1, bx, y2, dur_ms))
            ok += 1
        except InvalidDomain as exc:
            notes.append(f"浏览段第 {ok + 1} 次滑动被拒：{exc}")
            break
    elapsed = round(time.monotonic() - t0, 1)
    notes.append(f"浏览任务段：{ok} 次滑动 / {elapsed}s（目标 ≥10s，比例口径 {tw}x{th}）")
    return elapsed >= 10.0


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


def _stage_intent(deps: RunDeps, kind: ActionKind, reason: str) -> ActionIntent:
    """终态收尾动作（STOP/HOME 是生命周期动作：不带候选依据、不带业务坐标）。"""
    return ActionIntent(
        action_id=f"{deps.run_id}-{kind.value}-{deps.now_ns()}",
        run_id=deps.run_id, kind=kind, source_capture_id="terminal",
        state_epoch=getattr(deps.device, "state_epoch", 0), geometry_revision=0,
        deadline_ns=deps.now_ns() + 15_000_000_000, reason=reason)


def _read_last_activity(deps: RunDeps) -> str | None:
    """关 app 前读一次焦点 activity（pdd.sh L1622：按完 HOME 就只剩桌面了）。

    读不到不阻塞收尾（旧口径：`last_act=读不到` 也照发推送）。
    """
    try:
        fs = deps.device.focus()
    except Exception:
        return None
    return getattr(fs, "focused_activity", None) or None


def _apply_close_policy(deps: RunDeps, plan, notes: list) -> None:
    """下发 close_policy（迁移审计 G4：terminal_plan 早就算好却从未执行）。

    旧脚本收尾纪律（cmd_run L1628-1637）：
    - STOP_AND_HOME：force-stop + HOME（rc0 正常完成）；
    - HOME_ONLY：只按 HOME（rc≠0，B07：失败路径不 force-stop）；
    - STAY：lit2/4 手机停在当前屏等她，一个键都不放。
    单个动作失败只记 notes，不改业务 rc（终态收尾不影响判定，I11 同理）。
    """
    try:
        if plan.close_policy is ClosePolicy.STOP_AND_HOME:
            deps.device.execute(_stage_intent(deps, ActionKind.STOP, "正常完成，关掉 app"))
            deps.device.execute(_stage_intent(deps, ActionKind.HOME, "关 app 后回桌面"))
            notes.append("收尾：force-stop + HOME")
        elif plan.close_policy is ClosePolicy.HOME_ONLY:
            deps.device.execute(_stage_intent(deps, ActionKind.HOME, "失败收尾只按 HOME"))
            notes.append("收尾：HOME")
        else:                                     # STAY：lit2/4 一个键都不放
            notes.append("收尾：留在当前屏（lit2/4 不关 app）")
    except Exception as exc:                      # 收尾失败不污染业务结果
        notes.append(f"收尾动作失败（忽略）：{exc}")


def _final_scroll(deps: RunDeps, notes: list) -> None:
    """成功后的最终 20 次下滑（I06；pdd.sh scroll_phase L1458-1467）。

    比例口径同旧脚本 SWIPE_* 常量：x=0.75×w、y1=0.9375×h → y2=0.546875×h、
    300ms 按压、20 次、次间隔 1s。与浏览段的 800ms/15s 是两件事，不合并。
    失败只记 notes，不改业务 rc（收尾动作，判定早已完成）。
    """
    sleep = getattr(deps, "browse_sleep", None) or time.sleep
    tw = int(getattr(deps.device, "tap_width", 0) or 720)
    th = int(getattr(deps.device, "tap_height", 0) or 1280)
    if tw <= 0 or th <= 0:
        tw, th = 720, 1280
    bx, y1 = int(tw * 0.75), int(th * 0.9375)
    y2 = int(th * 0.546875)
    ok = 0
    for i in range(20):
        try:
            intent = ActionIntent(
                action_id=f"{deps.run_id}-final-scroll-{i}-{deps.now_ns()}",
                run_id=deps.run_id, kind=ActionKind.SWIPE,
                source_capture_id="terminal", state_epoch=getattr(deps.device, "state_epoch", 0),
                geometry_revision=0, deadline_ns=deps.now_ns() + 15_000_000_000,
                reason=f"最终下滑 {i + 1}/20（x=0.75 {y1}→{y2} 300ms）",
                source_candidate_id="final-scroll", target_key="final_scroll",
                expected_package="com.xunmeng.pinduoduo", required_window_kind=WindowKind.APP)
            deps.device.execute(intent, (bx, y1, bx, y2, 300))
            ok += 1
        except Exception as exc:
            notes.append(f"最终下滑第 {i + 1} 次被拒（忽略）：{exc}")
            break
        sleep(1.0)
    notes.append(f"最终下滑：{ok}/20（I06）")
