"""adb 设备适配（T06）：显式 serial、严格 PNG 解码、焦点分类保留三态。

runner 可注入（测试用假进程）；生产路径是 subprocess.run。
绝不自动选「第一台在线设备」——serial 必须显式给出（T06.2）。
"""

from __future__ import annotations

import re
import struct
import subprocess
from dataclasses import dataclass

from pddcheck.domain import (
    ActionIntent,
    ActionReceipt,
    Capture,
    ExecutionStatus,
    FocusState,
    InvalidDomain,
    WindowKind,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_FOCUS = re.compile(r"mCurrentFocus=.*?\s([\w.]+)/([\w.$]+)\}")
_RESUMED = re.compile(r"mResumedActivity.*?\s([\w.]+)/([\w.$]+)\}")


class AdbError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class PngDecodeError(AdbError):
    pass


def png_size(data: bytes) -> tuple[int, int]:
    """严格 PNG 头解码：magic + 首个 IHDR 的宽高。坏图/截断 → PngDecodeError。"""
    if len(data) < 24 or not data.startswith(PNG_MAGIC):
        raise PngDecodeError("png_bad_magic", f"len={len(data)}")
    length, ctype = struct.unpack(">I4s", data[8:16])
    if ctype != b"IHDR" or length != 13:
        raise PngDecodeError("png_no_ihdr", str(ctype))
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise PngDecodeError("png_bad_dimensions", f"{width}x{height}")
    return width, height


@dataclass(frozen=True, slots=True)
class Completed:
    rc: int
    out: bytes
    err: bytes


def _subprocess_runner(argv, timeout_s):
    p = subprocess.run(argv, capture_output=True, timeout=timeout_s, check=False)
    return Completed(p.returncode, p.stdout, p.stderr)


class AdbDevice:
    def __init__(self, serial: str, *, runner=None, timeout_s: float = 20.0,
                 pkg: str = "com.xunmeng.pinduoduo", now_ns=None,
                 home_activity: str | None = None) -> None:
        if not serial:
            raise AdbError("serial_required", "必须显式指定设备 serial，禁止自动选第一台")
        self.serial = serial
        self.pkg = pkg
        self.home_activity = home_activity
        self._run = runner or _subprocess_runner
        self._timeout_s = timeout_s
        self._now = now_ns or (lambda: 0)
        self.state_epoch = 0
        self.tap_width = 0
        self.tap_height = 0

    # ---- 基础 -------------------------------------------------------
    def _adb(self, *args: str) -> Completed:
        return self._run(["adb", "-s", self.serial, *args], self._timeout_s)

    def connect(self) -> str:
        c = self._adb("get-state")
        state = c.out.decode("utf-8", "replace").strip()
        if c.rc != 0:
            raise AdbError("adb_failed", c.err.decode("utf-8", "replace")[:200])
        if state == "unauthorized":
            raise AdbError("unauthorized", "设备未授权 USB 调试")
        if state == "offline":
            raise AdbError("offline", "设备离线")
        if state != "device":
            raise AdbError("bad_state", state)
        self.state_epoch += 1
        return state

    # ---- 观测 -------------------------------------------------------
    def focus(self) -> FocusState:
        c = self._adb("shell", "dumpsys", "window")
        text = c.out.decode("utf-8", "replace")
        m = _FOCUS.search(text)
        if not m:
            # 无斜杠焦点（如 Window{c485e35 u0 StatusBar}）：仍按状态栏识别；其余未知
            if "StatusBar" in text or "NotificationShade" in text:
                return FocusState(window_kind=WindowKind.STATUSBAR, sampled_ns=self._now())
            return FocusState(window_kind=WindowKind.UNKNOWN, sampled_ns=self._now())
        pkg, act = m.group(1), m.group(2)
        kind = self._classify(pkg, act, text)
        resumed = _RESUMED.search(text)
        return FocusState(window_kind=kind, sampled_ns=self._now(),
                          focused_package=pkg, focused_activity=act,
                          resumed_package=resumed.group(1) if resumed else None)

    def screenshot_bytes(self) -> bytes:
        """只读取一帧像素（PNG bytes）；坏图抛 AdbError（不拿旧值凑）。干跑/测量用。"""
        c = self._adb("exec-out", "screencap", "-p")
        if c.rc != 0:
            raise AdbError("screencap_failed", c.err.decode("utf-8", "replace")[:200])
        png_size(c.out)                     # 严格解码校验
        return c.out

    def _classify(self, pkg: str, act: str, text: str) -> WindowKind:
        if "keyguard" in act.lower() or "StatusBar" in pkg:
            return WindowKind.KEYGUARD if "keyguard" in act.lower() else WindowKind.STATUSBAR
        if pkg == self.pkg:
            return WindowKind.APP
        if "NotificationShade" in act or "StatusBar" in text:
            return WindowKind.STATUSBAR
        return WindowKind.FOREIGN

    def read_hierarchy(self) -> str:
        # 真机坑（T18a 实测）：`uiautomator dump /dev/tty` 在部分机型返回空，
        # 必须 dump 到文件再读。先试标准路径，空则回退文件法。
        c = self._adb("shell", "uiautomator", "dump", "/dev/tty")
        text = c.out.decode("utf-8", "replace")
        if c.rc == 0 and "<hierarchy" in text:
            return text
        remote = "/sdcard/pddcheck-dump.xml"
        d = self._adb("shell", "uiautomator", "dump", remote)
        if d.rc != 0:
            raise AdbError("hierarchy_failed",
                           d.err.decode("utf-8", "replace")[:200] or d.out.decode("utf-8", "replace")[:200])
        cat = self._adb("exec-out", "cat", remote)
        text = cat.out.decode("utf-8", "replace")
        if "<hierarchy" not in text:
            raise AdbError("hierarchy_empty", "dump 文件里没有 <hierarchy>")
        self._adb("shell", "rm", "-f", remote)     # 清理，别在手机上留垃圾
        return text

    def capture(self) -> Capture:
        t0 = self._now()
        fb = self.focus()
        c = self._adb("exec-out", "screencap", "-p")
        if c.rc != 0:
            raise AdbError("screencap_failed", c.err.decode("utf-8", "replace")[:200])
        w, h = png_size(c.out)                    # 严格解码：坏图当场抛，不拿旧尺寸凑
        self.tap_width, self.tap_height = w, h
        t1 = self._now()
        fa = self.focus()
        return Capture(
            run_id="adb", capture_id=f"cap-{t1}", state_epoch=self.state_epoch,
            capture_started_ns=t0, capture_finished_ns=t1,
            focus_before=fb, focus_after=fa,
            tap_width=w, tap_height=h, rotation=0,
            screenshot_encoding="png", capture_transport="adb",
            screenshot_width=w, screenshot_height=h,
        )

    # ---- 动作 -------------------------------------------------------
    def execute(self, intent: ActionIntent,
                point: tuple[int, ...] | None = None) -> ActionReceipt:
        now = self._now()
        if intent.state_epoch != self.state_epoch:
            return ActionReceipt(intent.action_id, ExecutionStatus.REJECTED, now, now,
                                 "epoch_stale")
        if now > intent.deadline_ns:
            return ActionReceipt(intent.action_id, ExecutionStatus.REJECTED, now, now,
                                 "deadline_exceeded")
        # 坐标缺失是调用方错误：派发前就拒绝，绝不发一个瞎点的动作
        if intent.kind.value == "tap" and (not point or len(point) != 2):
            return ActionReceipt(intent.action_id, ExecutionStatus.REJECTED, now, now,
                                 "tap_point_missing")
        if intent.kind.value == "swipe" and (not point or len(point) != 4):
            return ActionReceipt(intent.action_id, ExecutionStatus.REJECTED, now, now,
                                 "swipe_point_missing")
        # 动作前前台校验（T06.6 安全护栏）：业务动作必须落在预期包/窗口上，否则拒绝。
        # 真机干跑证实：裸坐标在错页会「命中」——这一层是最后防线。
        if intent.kind.value in ("tap", "swipe", "back"):
            try:
                fs = self.focus()
            except Exception:
                return ActionReceipt(intent.action_id, ExecutionStatus.REJECTED, now, now,
                                     "focus_unavailable")
            if intent.expected_package and fs.focused_package != intent.expected_package:
                return ActionReceipt(intent.action_id, ExecutionStatus.REJECTED, now, now,
                                     "wrong_window_package")
            if intent.required_window_kind is not None and fs.window_kind is not intent.required_window_kind:
                return ActionReceipt(intent.action_id, ExecutionStatus.REJECTED, now, now,
                                     "wrong_window_kind")
        try:
            c = self._dispatch(intent, point)
        except (OSError, subprocess.TimeoutExpired) as exc:
            # 超时/进程层失败：可能已发出也可能没发出——按 UNKNOWN 处理，不重发
            return ActionReceipt(intent.action_id, ExecutionStatus.UNKNOWN_EXECUTION,
                                 now, self._now(), "transport_uncertain", str(exc)[:200])
        if c.rc != 0:
            return ActionReceipt(intent.action_id, ExecutionStatus.UNKNOWN_EXECUTION,
                                 now, self._now(), "adb_rc", c.err.decode("utf-8", "replace")[:200])
        return ActionReceipt(intent.action_id, ExecutionStatus.ACKNOWLEDGED, now, self._now())

    def _dispatch(self, intent: ActionIntent, point: tuple[int, ...] | None) -> Completed:
        k = intent.kind.value
        if k == "tap":
            if not point or len(point) != 2:
                raise AdbError("tap_point_missing", "TAP 需要显式 (x, y)")
            return self._adb("shell", "input", "tap", str(point[0]), str(point[1]))
        if k == "swipe":
            if not point or len(point) != 4:
                raise AdbError("swipe_point_missing", "SWIPE 需要 (x1,y1,x2,y2)")
            return self._adb("shell", "input", "swipe",
                             *(str(v) for v in point), "300")
        if k == "back":
            return self._adb("shell", "input", "keyevent", "KEYCODE_BACK")
        if k == "home":
            return self._adb("shell", "input", "keyevent", "KEYCODE_HOME")
        if k == "wake":
            return self._adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        if k == "dismiss_keyguard":
            return self._adb("shell", "wm", "dismiss-keyguard")
        if k == "start":
            if not self.home_activity:
                raise AdbError("home_activity_missing", "必须显式 HOME_ACT 启动，禁止 monkey")
            return self._adb("shell", "am", "start", "-n", self.home_activity)
        if k == "stop":
            return self._adb("shell", "am", "force-stop", self.pkg)
        raise InvalidDomain(f"未知动作 {k}")
