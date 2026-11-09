"""日标记与兑换账本（T08，I10/I12/I13）。

- 日标记：`<证据根>/.done-<YYYY-MM-DD>` 存在即当天已完成（不重跑、不通知）；
- 账本：一个数字的文件（屏幕上「N天后可兑换」的 N）。口径（10-11 定案）：
  任何值都不挡路——读不到/垃圾/不存在一律当「没记过」，绝不能因此跳过当天。
"""

from __future__ import annotations

import re
from pathlib import Path

from pddcheck.storage.atomic import atomic_write_text

_NUM = re.compile(r"[0-9]+")


class DailyStore:
    def __init__(self, evidence_root: Path, ledger_path: Path) -> None:
        self.evidence_root = Path(evidence_root)
        self.ledger_path = Path(ledger_path)

    # ---- 日标记 -------------------------------------------------------
    def marker_path(self, business_date: str) -> Path:
        return self.evidence_root / f".done-{business_date}"

    def marker_exists(self, business_date: str) -> bool:
        return self.marker_path(business_date).exists()

    def write_marker(self, business_date: str) -> None:
        atomic_write_text(self.marker_path(business_date), "")

    # ---- 兑换账本（兼容旧 $HOME/Desktop/pdd-pause）--------------------
    def ledger_read(self) -> int | None:
        """读账本数字；不存在/空/垃圾 → None（不挡路，只当没记过）。"""
        try:
            text = self.ledger_path.read_text(encoding="utf-8")
        except OSError:
            return None
        m = _NUM.search(text)
        return int(m.group()) if m else None

    def ledger_write(self, value: int) -> bool:
        """写账本；返回是否真的写进去（写失败不改业务 rc，但 operational_status 可见）。"""
        try:
            atomic_write_text(self.ledger_path, f"{value}\n")
            return True
        except OSError:
            return False

    def ledger_clear(self) -> bool:
        return self.ledger_write(0)

    # ---- 证据保留（迁移审计 G9：旧 prune_evidence / KEEP_DAYS 口径）----
    def prune_evidence(self, keep_days: int) -> int:
        """删除证据根下 keep_days 天前的**一层日期目录**；返回删除数。

        旧口径（pdd.sh L1491-1494）：`find -mindepth 1 -maxdepth 1 -type d
        -mtime +KEEP_DAYS -exec rm -rf` —— 只删目录，`.done-*` 标记文件
        与证据根本身不动。keep_days<=0 或根不存在时一个都不删。
        """
        if keep_days <= 0:
            return 0
        import shutil
        import time as _time
        cutoff = _time.time() - keep_days * 86400
        removed = 0
        try:
            entries = list(self.evidence_root.iterdir())
        except OSError:
            return 0
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
                if entry.stat().st_mtime <= cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        return removed
