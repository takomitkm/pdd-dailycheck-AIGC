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
    focus_pdd = (0, b"mCurrentFocus=Window{a u0 com.xunmeng.pinduoduo/com.xunmeng.pinduoduo.ui.activity.HomeActivity}\n", b"")
    scripted = Scripted([
        (["adb", "-s", "ABC", "shell", "dumpsys", "window"], focus_pdd),
        (["adb", "-s", "ABC", "shell", "input", "tap"], (0, b"", b"")),
    ])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100)
    dev.state_epoch = 0
    r = dev.execute(intent(deadline=5000), (123, 456))
    assert r.status is ExecutionStatus.ACKNOWLEDGED
    assert scripted.calls[-1] == ["adb", "-s", "ABC", "shell", "input", "tap", "123", "456"]


def test_adb_tap_without_point_fails_closed():
    focus_pdd = (0, b"mCurrentFocus=Window{a u0 com.xunmeng.pinduoduo/com.xunmeng.pinduoduo.ui.activity.HomeActivity}\n", b"")
    dev = AdbDevice("ABC", runner=Scripted([(["adb"], focus_pdd)]), now_ns=lambda: 100)
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


def test_adb_action_guard_rejects_wrong_foreground():
    """T06.6 安全护栏：业务动作前校验前台包/窗口，错页一律拒绝。"""
    focus_other = (0, b"mCurrentFocus=Window{a u0 com.android.launcher3/com.android.launcher3.Launcher}\n", b"")
    scripted = Scripted([(["adb", "-s", "ABC", "shell", "dumpsys", "window"], focus_other)])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100)
    r = dev.execute(intent(deadline=5000), (100, 200))
    assert r.status is ExecutionStatus.REJECTED and r.error_code == "wrong_window_package"
    assert not any("input" in " ".join(c) for c in scripted.calls)   # 绝不发 tap


def test_adb_action_guard_allows_correct_foreground():
    focus_pdd = (0, b"mCurrentFocus=Window{a u0 com.xunmeng.pinduoduo/com.xunmeng.pinduoduo.ui.activity.HomeActivity}\n", b"")
    scripted = Scripted([
        (["adb", "-s", "ABC", "shell", "dumpsys", "window"], focus_pdd),
        (["adb", "-s", "ABC", "shell", "input", "tap"], (0, b"", b"")),
    ])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100)
    r = dev.execute(intent(deadline=5000), (100, 200))
    assert r.status is ExecutionStatus.ACKNOWLEDGED


def test_adb_screenshot_bytes_strict(tmp_path):
    scripted = Scripted([(["adb", "-s", "ABC", "exec-out", "screencap"], (0, _png(720, 1280), b""))])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100)
    data = dev.screenshot_bytes()
    assert data.startswith(b"\x89PNG") and len(data) > 20
    # 坏图 → 抛（不返回半截）
    bad = Scripted([(["adb", "-s", "ABC", "exec-out", "screencap"], (0, b"junk", b""))])
    with pytest.raises(PngDecodeError):
        AdbDevice("ABC", runner=bad, now_ns=lambda: 100).screenshot_bytes()


def test_adb_read_hierarchy_falls_back_to_file_when_tty_empty():
    """真机坑（T18a）：dump /dev/tty 返回空 → 必须回退 dump 到文件再 cat，并清理。"""
    xml = b"<hierarchy><node text='x' bounds='[0,0][1,1]'/></hierarchy>"
    scripted = Scripted([
        (["adb", "-s", "ABC", "shell", "uiautomator", "dump", "/dev/tty"], (0, b"", b"")),
        (["adb", "-s", "ABC", "shell", "uiautomator", "dump", "/sdcard/pddcheck-dump.xml"],
         (0, b"UI hierchary dumped to: /sdcard/pddcheck-dump.xml", b"")),
        (["adb", "-s", "ABC", "exec-out", "cat", "/sdcard/pddcheck-dump.xml"], (0, xml, b"")),
        (["adb", "-s", "ABC", "shell", "rm", "-f", "/sdcard/pddcheck-dump.xml"], (0, b"", b"")),
    ])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100)
    assert "<hierarchy" in dev.read_hierarchy()
    # 确认清理动作真的发了（不在手机上留垃圾）
    assert any("rm" in " ".join(c) for c in scripted.calls)


# ----------------------------------------------------- 冷启动组件名（11-10 rc7 回归）

MAIN = "com.xunmeng.pinduoduo/com.xunmeng.pinduoduo.ui.activity.MainFrameActivity"
HOME = "com.xunmeng.pinduoduo/com.xunmeng.pinduoduo.ui.activity.HomeActivity"


def test_adb_start_uses_pkg_prefixed_component():
    """11-10 rc7 根因回归：`am start -n` 必须「包名/Activity」，裸类名 am 解析不到
    → 冷启动从来没成功过（只有手机恰好在 PDD 页时才碰巧跑通）。"""
    scripted = Scripted([
        (["adb", "-s", "ABC", "shell", "am", "start", "-n", MAIN],
         (0, b"Starting: Intent { cmp=" + MAIN.encode() + b" }\n", b"")),
    ])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100,
                    home_activity="com.xunmeng.pinduoduo.ui.activity.HomeActivity",
                    launch_activity="com.xunmeng.pinduoduo.ui.activity.MainFrameActivity")
    r = dev.execute(intent(kind=ActionKind.START, deadline=5000), None)
    assert r.status is ExecutionStatus.ACKNOWLEDGED
    assert scripted.calls[-1] == ["adb", "-s", "ABC", "shell", "am", "start", "-n", MAIN]


def test_adb_start_falls_back_to_home_activity_when_launch_fails():
    """主入口起不来（am 打 Error）→ 退 HomeActivity（旧脚本 HOME_ACT/HOME_ACT_ALT 同序）。"""
    scripted = Scripted([
        (["adb", "-s", "ABC", "shell", "am", "start", "-n", MAIN],
         (1, b"", b"Error: Activity class {...} does not exist.\n")),
        (["adb", "-s", "ABC", "shell", "am", "start", "-n", HOME],
         (0, b"Starting: Intent { cmp=" + HOME.encode() + b" }\n", b"")),
    ])
    dev = AdbDevice("ABC", runner=scripted, now_ns=lambda: 100,
                    home_activity="com.xunmeng.pinduoduo.ui.activity.HomeActivity",
                    launch_activity="com.xunmeng.pinduoduo.ui.activity.MainFrameActivity")
    r = dev.execute(intent(kind=ActionKind.START, deadline=5000), None)
    assert r.status is ExecutionStatus.ACKNOWLEDGED
    assert scripted.calls[-1][-1] == HOME            # 退到了 HomeActivity


def test_adb_start_without_activity_fails_closed():
    dev = AdbDevice("ABC", runner=Scripted([(["adb"], (0, b"", b""))]), now_ns=lambda: 100)
    with pytest.raises(AdbError, match="home_activity"):
        dev.execute(intent(kind=ActionKind.START, deadline=5000), None)
