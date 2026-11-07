"""能力集合（I03）：设备命令与离线命令构造不同能力集。

离线命令（replay/report/check-config/doctor）**拿不到** DevicePort——不是靠一个
run-time 布尔，而是构造期就没有这个能力（拿到 None 或抛错）。
"""

from __future__ import annotations

from enum import StrEnum


class Capability(StrEnum):
    READ_STATE = "read_state"          # 读日标记/账本/journal
    WRITE_STATE = "write_state"
    OCR = "ocr"                        # 识别已落盘图像
    DEVICE_OBSERVE = "device_observe"  # 采集/焦点/层级
    DEVICE_ACT = "device_act"          # 点击/滑动/按键/启动
    NOTIFY = "notify"
    REPLAY = "replay"


_OFFLINE = frozenset({
    Capability.READ_STATE, Capability.WRITE_STATE, Capability.OCR,
    Capability.NOTIFY, Capability.REPLAY,
})
_DEVICE = _OFFLINE | {Capability.DEVICE_OBSERVE, Capability.DEVICE_ACT}


def offline_capabilities() -> frozenset[Capability]:
    return _OFFLINE


def device_capabilities() -> frozenset[Capability]:
    return _DEVICE


class CapabilityDenied(PermissionError):
    """在缺少某能力的能力集里请求了它——构造期就拒绝（I03）。"""
