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
