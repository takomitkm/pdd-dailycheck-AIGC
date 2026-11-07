"""T06：设备端口测试——fake 语义（重复/deadline/epoch/丢响应/重启）、
adb argv 与显式 serial、严格 PNG 解码、焦点三态、能力边界。"""

from __future__ import annotations

import pytest

from pddcheck.device import (
    AdbDevice,
    AdbError,
    Capability,
    FakeDevice,
    PngDecodeError,
    device_capabilities,
    offline_capabilities,
    png_size,
)
from pddcheck.domain import (
    ActionIntent,
    ActionKind,
    ExecutionStatus,
    WindowKind,
)


def intent(action_id="a1", *, epoch=0, deadline=10_000, kind=ActionKind.TAP,
           run_id="r1") -> ActionIntent:
    kwargs = dict(action_id=action_id, run_id=run_id, kind=kind,
                  source_capture_id="cap1", state_epoch=epoch,
                  geometry_revision=1, deadline_ns=deadline, reason="test")
    if kind in (ActionKind.TAP, ActionKind.SWIPE, ActionKind.BACK):
        kwargs.update(expected_package="com.xunmeng.pinduoduo",
                      required_window_kind=WindowKind.APP,
                      source_candidate_id="cand1")
    return ActionIntent(**kwargs)


# --------------------------------------------------------------- fake 语义


def test_fake_tap_acknowledged():
    dev = FakeDevice(now_ns=lambda: 1000)
    r = dev.execute(intent(deadline=5000), (100, 200))
    assert r.status is ExecutionStatus.ACKNOWLEDGED and len(dev.executed) == 1


def test_fake_duplicate_action_id_rejected_not_reexecuted():
    dev = FakeDevice(now_ns=lambda: 1000)
    dev.execute(intent("dup", deadline=5000), (1, 1))
    r = dev.execute(intent("dup", deadline=5000), (1, 1))
    assert r.status is ExecutionStatus.REJECTED and r.error_code == "duplicate_action_id"
    assert len(dev.executed) == 1


def test_fake_deadline_exceeded_not_executed():
    dev = FakeDevice(now_ns=lambda: 99_999)
    r = dev.execute(intent(deadline=1000), (1, 1))
    assert r.status is ExecutionStatus.REJECTED and r.error_code == "deadline_exceeded"
    assert dev.executed == []


def test_fake_stale_epoch_rejected():
    dev = FakeDevice(now_ns=lambda: 1000)
    dev.bump_epoch()                       # epoch 变 1
    r = dev.execute(intent(epoch=0, deadline=5000), (1, 1))
    assert r.status is ExecutionStatus.REJECTED and r.error_code == "epoch_stale"


def test_fake_lost_response_is_unknown_execution_not_retried():
    dev = FakeDevice(now_ns=lambda: 1000)
    dev.inject_failure("lost_response")
    r = dev.execute(intent(deadline=5000), (1, 1))
    assert r.status is ExecutionStatus.UNKNOWN_EXECUTION and r.error_code == "lost_response"
    # 已执行但响应丢失：记录在案，绝不自动重发
    assert len(dev.executed) == 1


def test_fake_server_restart_bumps_epoch_and_does_not_execute():
    dev = FakeDevice(now_ns=lambda: 1000)
    dev.inject_failure("server_restart")
    before = dev.state_epoch
    r = dev.execute(intent(deadline=5000), (1, 1))
    assert r.status is ExecutionStatus.UNKNOWN_EXECUTION
    assert dev.state_epoch == before + 1 and dev.executed == []
    # 旧 epoch 的后续意图全部作废
    r2 = dev.execute(intent("a2", epoch=before, deadline=5000), (1, 1))
    assert r2.error_code == "epoch_stale"


# --------------------------------------------------------------- 能力边界


def test_offline_capabilities_lack_device_act():
    caps = offline_capabilities()
    assert Capability.DEVICE_ACT not in caps and Capability.DEVICE_OBSERVE not in caps
    assert Capability.REPLAY in caps and Capability.OCR in caps


def test_device_capabilities_superset_of_offline():
    assert offline_capabilities() <= device_capabilities()
    assert Capability.DEVICE_ACT in device_capabilities()


# --------------------------------------------------------------- PNG 严格解码


def _png(width: int, height: int) -> bytes:
    import struct
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + chunk + b"truncated-rest"


def test_png_size_parses_width_height():
    assert png_size(_png(720, 1280)) == (720, 1280)


def test_png_size_rejects_bad_magic():
    with pytest.raises(PngDecodeError, match="png_bad_magic"):
        png_size(b"not a png at all")


def test_png_size_rejects_truncated():
    with pytest.raises(PngDecodeError):
        png_size(b"\x89PNG\r\n\x1a\n\x00\x00")


def test_png_size_rejects_zero_dimensions():
    with pytest.raises(PngDecodeError, match="dimensions"):
        png_size(_png(0, 1280))


# --------------------------------------------------------------- adb 适配


class Scripted:
    """按 argv 匹配返回预设 Completed。"""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, argv, timeout_s):
        from pddcheck.device.adb import Completed
        self.calls.append(argv)
        for prefix, resp in self.responses:
            if argv[:len(prefix)] == prefix:
                return Completed(*resp)
        return Completed(1, b"", b"unexpected argv")


def test_adb_requires_explicit_serial():
    with pytest.raises(AdbError, match="serial"):
        AdbDevice("")


def test_adb_connect_reports_states():
    dev = AdbDevice("ABC123", runner=Scripted([(["adb", "-s", "ABC123", "get-state"], (0, b"device\n", b""))]))
    assert dev.connect() == "device"
    dev = AdbDevice("ABC", runner=Scripted([(["adb"], (0, b"unauthorized\n", b""))]))
    with pytest.raises(AdbError, match="unauthorized"):
        dev.connect()
    dev = AdbDevice("ABC", runner=Scripted([(["adb"], (0, b"offline\n", b""))]))
    with pytest.raises(AdbError, match="offline"):
        dev.connect()


def test_adb_tap_builds_argv_with_coords():
    scripted = Scripted([(["adb"], (0, b"", b""))])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100)
    dev.state_epoch = 0
    r = dev.execute(intent(deadline=5000), (123, 456))
    assert r.status is ExecutionStatus.ACKNOWLEDGED
    assert scripted.calls[-1] == ["adb", "-s", "ABC", "shell", "input", "tap", "123", "456"]


def test_adb_tap_without_point_fails_closed():
    dev = AdbDevice("ABC", runner=Scripted([(["adb"], (0, b"", b""))]), now_ns=lambda: 100)
    r = dev.execute(intent(deadline=5000), None)
    assert r.status is ExecutionStatus.REJECTED and r.error_code == "tap_point_missing"


def test_adb_capture_strict_png_and_focus_classification():
    dumpsys = (0, (
        b"mCurrentFocus=Window{abc u0 com.xunmeng.pinduoduo/com.xunmeng.pinduoduo.ui.activity.HomeActivity}\n"
        b"mResumedActivity: ActivityRecord{x u0 com.xunmeng.pinduoduo/.MainActivity t1}\n"
    ), b"")
    scripted = Scripted([
        (["adb", "-s", "ABC", "shell", "dumpsys", "window"], dumpsys),
        (["adb", "-s", "ABC", "exec-out", "screencap"], (0, _png(720, 1280), b"")),
    ])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100)
    cap = dev.capture()
    assert (cap.tap_width, cap.tap_height) == (720, 1280)
    assert cap.focus_before.window_kind is WindowKind.APP
    assert cap.focus_before.focused_package == "com.xunmeng.pinduoduo"


def test_adb_capture_bad_png_raises_not_fake():
    dumpsys = (0, b"no focus here\n", b"")
    scripted = Scripted([
        (["adb", "-s", "ABC", "shell", "dumpsys", "window"], dumpsys),
        (["adb", "-s", "ABC", "exec-out", "screencap"], (0, b"garbage", b"")),
    ])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100)
    with pytest.raises(PngDecodeError):
        dev.capture()
