"""T14(2/2)：run 编排端到端——FakeDevice/FakeScreen/FakeClock 驱动全流程。"""

from __future__ import annotations

import json

from pddcheck.cli.exits import ExitCode
from pddcheck.device import FakeDevice
from pddcheck.device.capabilities import Capability, offline_capabilities
from pddcheck.notify import NotificationSender
from pddcheck.storage import DailyStore, Journal, LockBusy
from pddcheck.workflow.flow import RunDeps, run_once
from pddcheck.workflow.verify import VerifyObservation, VerifyStage


class Screen:
    def __init__(self, facts, obs=()):
        self._facts = facts
        self._obs = tuple(obs)

    def light_facts(self):
        return dict(self._facts)

    def post_tap_observations(self):
        return self._obs


def sender(status=200, body='{"code": 0}'):
    return NotificationSender(transport=lambda url, t: (status, body))


def deps(tmp_path, *, facts=None, obs=(), device=None, force=False,
         lease_factory=None, notifier=None, endpoint="http://stub/send"):
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    return RunDeps(
        device=device or FakeDevice(now_ns=lambda: 1000),
        screen=Screen(facts or {}, obs),
        store=store,
        journal=Journal(tmp_path / "journal" / "a.jsonl"),
        notifier=notifier or sender(),
        endpoint=endpoint,
        evidence_dir=str(tmp_path / "runs" / "d"),
        business_date="2026-11-07",
        run_id="run-1",
        now_ns=lambda: 1000,
        lease_factory=lease_factory,
        force=force,
    )


# --------------------------------------------------------------- 路径


def test_marker_present_skips_without_device_actions(tmp_path):
    d = deps(tmp_path)
    d.store.write_marker("2026-11-07")
    out = run_once(d)
    assert out.exit_code is ExitCode.OK and out.skipped == "daily_marker"
    assert d.device.executed == []                      # 零设备动作


def test_force_overrides_marker_only(tmp_path):
    d = deps(tmp_path, facts={"done_text": "今日已点亮"}, force=True)
    d.store.write_marker("2026-11-07")
    out = run_once(d)
    assert out.exit_code is ExitCode.OK and out.lit == 1 and out.skipped is None
    assert out.marker_written


def test_lock_busy_returns_75(tmp_path):
    def busy():
        raise LockBusy("busy")
    out = run_once(deps(tmp_path, lease_factory=busy))
    assert out.exit_code is ExitCode.LOCK_BUSY and out.skipped == "lock_busy"


def test_done_text_is_lit1_and_writes_marker(tmp_path):
    out = run_once(deps(tmp_path, facts={"done_text": "5折 最高减15元 已使用"}))
    assert out.exit_code is ExitCode.OK and out.lit == 1
    assert out.marker_written and out.ledger_written == 0
    assert out.title == "PDD 已使用"


def test_exchange_is_lit2_stays(tmp_path):
    out = run_once(deps(tmp_path, facts={"exchange_text": "立即兑换", "before_count": 4}))
    assert out.exit_code is ExitCode.OK and out.lit == 2
    assert not out.marker_written and out.close_policy == "stay"


def test_pending_is_lit4_records_ledger(tmp_path):
    out = run_once(deps(tmp_path, facts={"pend_text": "待兑换", "pend_days": 3}))
    assert out.exit_code is ExitCode.OK and out.lit == 4       # pend：进程码 0
    assert out.ledger_written == 3 and out.marker_written


def test_counter_decrease_is_lit3_success(tmp_path):
    obs = (VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=3),)
    out = run_once(deps(tmp_path, facts={"before_count": 4, "tap_point": (100, 900)}, obs=obs))
    assert out.exit_code is ExitCode.OK and out.lit == 3
    assert out.marker_written and out.close_policy == "stop_and_home"


def test_counter_unchanged_is_rc6_no_marker(tmp_path):
    obs = (VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=4),)
    out = run_once(deps(tmp_path, facts={"before_count": 4, "tap_point": (100, 900)}, obs=obs))
    assert out.exit_code is ExitCode.LIGHT_NOT_APPLIED and out.rc == 6
    assert not out.marker_written and out.close_policy == "home_only"


def test_unknown_execution_not_retried(tmp_path):
    dev = FakeDevice(now_ns=lambda: 1000)
    dev.inject_failure("lost_response")
    out = run_once(deps(tmp_path, facts={"before_count": 4, "tap_point": (1, 1)}, device=dev))
    assert out.exit_code is ExitCode.LIGHT_NOT_APPLIED and out.rc == 6
    assert len(dev.executed) == 1                          # 只发了那一枪，没有重发


def test_notify_failure_does_not_change_business_rc(tmp_path):
    obs = (VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=3),)
    out = run_once(deps(tmp_path, facts={"before_count": 4, "tap_point": (1, 1)}, obs=obs,
                       notifier=sender(500, "boom")))
    assert out.exit_code is ExitCode.OK and out.lit == 3   # 业务成功不受推送失败影响
    assert out.delivered == "http_error"


def test_no_endpoint_means_no_send_but_success(tmp_path):
    obs = (VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=3),)
    out = run_once(deps(tmp_path, facts={"before_count": 4, "tap_point": (1, 1)}, obs=obs,
                       endpoint=None))
    assert out.exit_code is ExitCode.OK and out.delivered == "no_endpoint"


def test_journal_has_intent_and_receipt(tmp_path):
    obs = (VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=3),)
    d = deps(tmp_path, facts={"before_count": 4, "tap_point": (1, 1)}, obs=obs)
    run_once(d)
    entries = d.journal.entries()
    kinds = [e.kind for e in entries]
    assert kinds == ["intent", "receipt"]


def test_offline_capabilities_never_include_device_act():
    # 端到端跑完后仍确认能力边界：离线集不含 DEVICE_ACT（防止 run 逻辑被离线命令复用）
    assert Capability.DEVICE_ACT not in offline_capabilities()
