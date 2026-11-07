"""notify：推送渲染与单次发送（T10，契约 §4/§10）。

- render.py：标题/正文纯渲染（正文逐字对齐 cmd_run 的 case $lit 五个分支）；
- sender.py：单次 HTTP 适配——一次 attempt、15s 级 deadline、传输失败不影响业务
  rc（I11）、成功判定走传输+HTTP+JSON 业务码（D07）、端点值永不出现在错误文本里。
"""

from pddcheck.notify.render import NotifyInput, render_notification
from pddcheck.notify.sender import (
    DeliveryResult,
    DeliveryStatus,
    NotificationSender,
    read_endpoint_file,
)

__all__ = [
    "NotifyInput",
    "render_notification",
    "DeliveryResult",
    "DeliveryStatus",
    "NotificationSender",
    "read_endpoint_file",
]
