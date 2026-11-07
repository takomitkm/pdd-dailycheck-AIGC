"""退出码合同（T14）：旧语义逐条保留 + 新 75（并发抢锁）。

| rc | 含义                         | 业务后果 |
|----|------------------------------|----------|
| 0  | 正常完成（lit 0/1/2/3）      | 写标记/账本 |
| 1  | 无法核实（verify 未过）       | 不写标记 → 映射推送 rc6 |
| 2  | 设备掉线/连接失败             | preflight 不虚造设备动作 |
| 3  | 手机锁屏/唤醒失败             | preflight 不虚造设备动作 |
| 4  | 点亮任务已完成待兑换          | 写标记，账本记 pend |
| 5  | 关键元素/步骤定位失败         | 不写标记 |
| 6  | 已点亮但进度未变（点没打进去） | 不写标记（对用户回报的 rc） |
| 69 | 缺 adb/依赖                   | 零动作、静默 |
| 73 | 配置/校验失败                 | 零动作、静默 |
| 75 | 并发抢锁失败（新）            | 零动作、静默 |
| 78 | 环境预检失败                  | 零动作、静默 |
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    UNVERIFIED = 1
    DEVICE_GONE = 2
    LOCKED = 3
    PENDING = 4
    LOCATE_FAILED = 5
    LIGHT_NOT_APPLIED = 6
    NO_ADB = 69
    CONFIG_INVALID = 73
    LOCK_BUSY = 75
    PRECHECK_FAILED = 78


# 早退码：收尾段之前返回，零设备动作；69/73/75/78 静默，2/3 有对应通知
EARLY_EXIT = frozenset({ExitCode.DEVICE_GONE, ExitCode.LOCKED,
                        ExitCode.NO_ADB, ExitCode.CONFIG_INVALID,
                        ExitCode.LOCK_BUSY, ExitCode.PRECHECK_FAILED})
SILENT_EXIT = frozenset({ExitCode.NO_ADB, ExitCode.CONFIG_INVALID,
                         ExitCode.LOCK_BUSY, ExitCode.PRECHECK_FAILED})

EXIT_TABLE: dict[ExitCode, str] = {
    ExitCode.OK: "正常完成",
    ExitCode.UNVERIFIED: "点亮无法核实",
    ExitCode.DEVICE_GONE: "设备掉线",
    ExitCode.LOCKED: "手机锁屏",
    ExitCode.PENDING: "点亮任务已完成待兑换",
    ExitCode.LOCATE_FAILED: "关键元素定位失败",
    ExitCode.LIGHT_NOT_APPLIED: "已点亮但进度未变",
    ExitCode.NO_ADB: "缺 adb/依赖",
    ExitCode.CONFIG_INVALID: "配置校验失败",
    ExitCode.LOCK_BUSY: "并发抢锁失败",
    ExitCode.PRECHECK_FAILED: "环境预检失败",
}


def exit_for_outcome(*, rc: int, lit: int | None) -> ExitCode:
    """把判定核/终态的输出映射成进程退出码（用于测试与真实退出）。"""
    if rc == 0:
        return ExitCode.OK
    if rc == 4:
        return ExitCode.PENDING
    if rc == 1:
        return ExitCode.UNVERIFIED
    if rc == 5:
        return ExitCode.LOCATE_FAILED
    if rc == 6:
        return ExitCode.LIGHT_NOT_APPLIED
    # 其它已定义码原样透传
    try:
        return ExitCode(rc)
    except ValueError:
        return ExitCode.UNVERIFIED
