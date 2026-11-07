"""动作 journal：intent/receipt 的 durable 追加（契约 §10，I15）。

- 每条一行 JSON（schema_version + 时间 + 内容）；
- record_intent 必须在底层动作**之前**持久化（先记账后开枪）；
- 恢复方读 unresolved：有 intent 没有 receipt 的 LIGHT/TAKE 记录；
- 本地 JSONL 不是远端事务日志——不宣称 exactly-once，只保证本机顺序与可见性。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from pddcheck.storage.atomic import atomic_write_text

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class JournalEntry:
    seq: int
    kind: str                      # intent | receipt | outcome
    payload: dict


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, kind: str, payload: dict) -> JournalEntry:
        seq = self._next_seq()
        entry = JournalEntry(seq=seq, kind=kind,
                             payload={"schema_version": SCHEMA_VERSION, **payload})
        line = json.dumps({"seq": seq, "kind": kind, "payload": entry.payload},
                          ensure_ascii=False) + "\n"
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return entry

    def record_intent(self, action_id: str, kind: str, detail: dict) -> JournalEntry:
        return self._append("intent", {"action_id": action_id, "action_kind": kind, **detail})

    def record_receipt(self, action_id: str, status: str, error_code: str | None) -> JournalEntry:
        return self._append("receipt", {"action_id": action_id, "status": status,
                                        "error_code": error_code})

    def _next_seq(self) -> int:
        return sum(1 for _ in self._iter_lines()) + 1

    def entries(self) -> tuple[JournalEntry, ...]:
        out = []
        for line_no, raw in enumerate(self._iter_lines(), 1):
            try:
                obj = json.loads(raw)
                out.append(JournalEntry(seq=int(obj.get("seq", line_no)),
                                        kind=str(obj.get("kind", "")),
                                        payload=dict(obj.get("payload", {}))))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue    # 半截行（崩溃残留）：跳过不挡路，恢复方按缺条目处理
        return tuple(out)

    def unresolved_intents(self) -> tuple[JournalEntry, ...]:
        """有 intent 没有 receipt 的条目（跨运行索引的存储半边；跨日/跨 release 由调用方组合）。"""
        seen_receipts = {e.payload.get("action_id") for e in self.entries() if e.kind == "receipt"}
        return tuple(e for e in self.entries()
                     if e.kind == "intent" and e.payload.get("action_id") not in seen_receipts)

    def _iter_lines(self):
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            yield from fh


def write_head(path: Path, payload: dict) -> None:
    """journal 头部信息（run_id/版本等）——原子写，重建索引用。"""
    atomic_write_text(path, json.dumps({"schema_version": SCHEMA_VERSION, **payload},
                                       ensure_ascii=False, indent=1))
