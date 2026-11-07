"""device：设备端口与适配（T06）。业务层只依赖 ports 的协议，不摸 adb 细节。

- ports.py：DevicePort/ObservationPort 协议 + 能力集合（I03 能力边界）；
- fake.py：协议夹具——重复动作/deadline/失效 epoch/丢响应/服务重启全部可注入；
- adb.py：adbutils/adb 适配（显式 serial、严格 PNG 解码、焦点/层级独立时间戳）。
"""

from pddcheck.device.adb import AdbDevice, AdbError, PngDecodeError, png_size
from pddcheck.device.capabilities import Capability, device_capabilities, offline_capabilities
from pddcheck.device.fake import FakeDevice
from pddcheck.device.ports import DevicePort, ObservationPort

__all__ = [
    "Capability",
    "device_capabilities",
    "offline_capabilities",
    "DevicePort",
    "ObservationPort",
    "FakeDevice",
    "AdbDevice",
    "AdbError",
    "PngDecodeError",
    "png_size",
]
