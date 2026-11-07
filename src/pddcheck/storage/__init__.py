"""storage：状态持久化（T08，契约 §10）。

- atomic.py：temp→flush/fsync→os.replace→目录 fsync 的原子写；
- lock.py：按设备的 flock 运行锁（POSIX；Windows 仅类型占位，生产目标是 Debian）；
- daily.py：日标记与兑换账本的兼容读写（账本只有一个数字，任何值不挡路，I12）；
- journal.py：动作意图/回执的 durable 追加（重启后只读核实，不自动重发，I15）。
路径全部由调用方注入——本包不读 HOME、不读环境。
"""

from pddcheck.storage.atomic import atomic_write, atomic_write_text
from pddcheck.storage.daily import DailyStore
from pddcheck.storage.errors import LockBusy
from pddcheck.storage.journal import Journal, JournalEntry

try:                                   # fcntl 仅 POSIX；Windows 收集期不炸
    from pddcheck.storage.lock import RunLease, acquire_run_lease
    _HAS_LOCK = True
except ImportError:                    # pragma: no cover - Windows smoke 环境
    _HAS_LOCK = False

    class RunLease:                    # 类型占位：非 POSIX 上不可实例化
        def __init__(self, *a, **k):
            raise RuntimeError("运行锁仅支持 POSIX（fcntl）")

    def acquire_run_lease(*a, **k):
        raise RuntimeError("运行锁仅支持 POSIX（fcntl）")

__all__ = [
    "atomic_write",
    "atomic_write_text",
    "DailyStore",
    "Journal",
    "JournalEntry",
    "LockBusy",
    "RunLease",
    "acquire_run_lease",
]
