"""存储层错误类型（与平台无关，Windows 也能导入）。"""

from __future__ import annotations

from pddcheck.domain.errors import DomainError


class LockBusy(DomainError):
    """另一个实例持有运行锁（映射旧 rc75 语义）。"""
