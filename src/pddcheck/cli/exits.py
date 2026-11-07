"""退出码合同（T14）：旧语义逐条保留 + 新 75（并发抢锁）。

| rc | 含义                         | 业务后果 |
|----|------------------------------|----------|
| 0  | 正常完成（lit 0/1/2/3/4）    | 写标记/账本（pend=lit4 也是 0） |
| 1  | 无法核实（内部 verify 未过）   | 映射为进程码 6 |
| 2  | 设备掉线/连接失败             | preflight 不虚造设备动作 |
| 3  | 手机锁屏/唤醒失败             | preflight 不虚造设备动作 |
| 4  | 入口失败（点入口没进活动页）   | 不写标记 |
| 5  | 关键元素/步骤定位失败         | 不写标记 |
| 6  | 已点亮但进度未变/无法核实      | 不写标记（对用户回报的 rc） |
| 7  | launch 后焦点不是 PDD         | 不写标记 |
| 69 | 缺 adb/依赖                   | 零动作、静默 |
| 73 | 状态/证据目录创建失败          | 不虚称写入 |
| 75 | 并发抢锁失败（新）             | 零动作、静默 |
| 78 | 环境预检/配置/OCR 不可用       | 零动作、静默 |
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    UNVERIFIED = 1
    DEVICE_GONE = 2
    LOCKED = 3
    ENTRY_FAILED = 4
    LOCATE_FAILED = 5
    LIGHT_NOT_APPLIED = 6
    FOCUS_WRONG = 7
    NO_ADB = 69
    STATE_DIR_FAILED = 73
    LOCK_BUSY = 75
    PRECHECK_FAILED = 78


# 早退码：收尾段之前返回，零设备动作；69/73/75/78 静默，2/3 有对应通知
EARLY_EXIT = frozenset({ExitCode.DEVICE_GONE, ExitCode.LOCKED,
                        ExitCode.NO_ADB, ExitCode.STATE_DIR_FAILED,
                        ExitCode.LOCK_BUSY, ExitCode.PRECHECK_FAILED})
SILENT_EXIT = frozenset({ExitCode.NO_ADB, ExitCode.STATE_DIR_FAILED,
                         ExitCode.LOCK_BUSY, ExitCode.PRECHECK_FAILED})

EXIT_TABLE: dict[ExitCode, str] = {
    ExitCode.OK: "正常完成",
    ExitCode.UNVERIFIED: "无法核实",
    ExitCode.DEVICE_GONE: "设备掉线",
    ExitCode.LOCKED: "手机锁屏",
    ExitCode.ENTRY_FAILED: "入口失败",
    ExitCode.LOCATE_FAILED: "关键元素定位失败",
    ExitCode.LIGHT_NOT_APPLIED: "已点亮但进度未变/无法核实",
    ExitCode.FOCUS_WRONG: "launch 后焦点不是 PDD",
    ExitCode.NO_ADB: "缺 adb/依赖",
    ExitCode.STATE_DIR_FAILED: "状态/证据目录创建失败",
    ExitCode.LOCK_BUSY: "并发抢锁失败",
    ExitCode.PRECHECK_FAILED: "环境预检/配置/OCR 不可用",
}


def exit_for_outcome(*, rc: int, lit: int | None) -> ExitCode:
    """把判定核/终态的业务 rc 映射成进程退出码。

    内部 verify_light 的「未过」是 rc=1，但对用户是 6（LIGHT_NOT_APPLIED）；
    pend 是 lit=4 而 rc=0（进程码 0）。
    """
    if rc == 1:
        return ExitCode.LIGHT_NOT_APPLIED
    try:
        return ExitCode(rc)
    except ValueError:
        return ExitCode.UNVERIFIED
