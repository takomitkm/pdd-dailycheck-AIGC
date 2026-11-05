"""Fake 公共件合同测试：未知操作必须失败、Recording 可断言、时钟可推进。"""

from __future__ import annotations

import pytest

from pddcheck.domain import (
    ActionIntent,
    ActionKind,
    Deadline,
    ExecutionStatus,
)
from tests.support.clock import FakeClock
from tests.support.fakes import FakeDevice, RecordingNotifier


def make_intent(action_id: str = "a1") -> ActionIntent:
    return ActionIntent(
        action_id=action_id,
        run_id="run-1",
        kind=ActionKind.TAP,
        source_capture_id="cap-1",
        state_epoch=3,
        geometry_revision=0,
        deadline_ns=9000,
        reason="测试",
        source_candidate_id="c1",
        expected_package="com.xunmeng.pinduoduo",
        required_window_kind=__import__("pddcheck.domain", fromlist=["WindowKind"]).WindowKind.APP,
    )


def test_fake_device_unknown_intent_fails_loudly():
    dev = FakeDevice()
    with pytest.raises(AssertionError, match="没有为"):
        dev.execute_once(make_intent(), Deadline(9000))


def test_fake_device_follows_script_and_records():
    clock = FakeClock(start_ns=100)
    dev = FakeDevice()
    dev.attach_clock(clock)
    dev.script(ActionKind.TAP, ExecutionStatus.ACKNOWLEDGED)
    receipt = dev.execute_once(make_intent("a2"), clock.deadline(5000))
    assert receipt.status is ExecutionStatus.ACKNOWLEDGED
    assert [i.action_id for i in dev.intents] == ["a2"]
    stale = clock.deadline(5000)  # 现在=100 时的截止；推进后即过期
    clock.advance_ns(10_000)
    with pytest.raises(TimeoutError):
        dev.execute_once(make_intent("a3"), stale)


def test_recording_notifier_never_sends_network():
    notifier = RecordingNotifier()
    class Req:
        title = "PDD ✅"
    assert notifier.send_once(Req()) == "acknowledged"
    assert notifier.attempts == ["PDD ✅"]


def test_fake_clock_monotonic_only():
    clock = FakeClock()
    clock.advance_ns(5)
    with pytest.raises(ValueError):
        clock.advance_ns(-1)
    assert clock.now_ns() == 6
