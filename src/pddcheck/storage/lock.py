"""按设备的 flock 运行锁（契约 §10）。

- 锁路径由调用方注入（稳定绝对路径，按 device_id 命名）；
- flock -n：拿不到立刻失败（rc75 语义），绝不排队等着错——并发沙箱腐坏的教训
  在 runner 层验证过同一模式；
- 句柄在 RunLease 存活期保持打开：进程活着锁就在，worker 继承同一 open
  file description（LeaseGuard 语义的存储层部分）。
"""

from __future__ import annotations

import fcntl
from pathlib import Path

from pddcheck.domain.errors import DomainError


class LockBusy(DomainError):
    """另一个实例持有运行锁（映射旧 rc75 语义）。"""


class RunLease:
    """持有期 = 锁持有期；close/with-exit 释放。"""

    def __init__(self, path: Path, device_id: str) -> None:
        self.path = Path(path)
        self.device_id = device_id
        self._fh = None

    def release(self) -> None:
        if self._fh is not None:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "RunLease":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def acquire_run_lease(lock_path: Path, device_id: str, *, blocking: bool = False) -> RunLease:
    """拿运行锁。blocking=False 时拿不到抛 LockBusy（第二个实例快速退出）。"""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+")
    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    try:
        fcntl.flock(fh, flags)
    except OSError as exc:
        fh.close()
        raise LockBusy(f"运行锁被占：{lock_path}（{exc}）") from exc
    lease = RunLease(lock_path, device_id)
    lease._fh = fh
    return lease
