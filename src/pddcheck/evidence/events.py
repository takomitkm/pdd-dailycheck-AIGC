"""JSONL 事件流（T09）：seq 单调、崩溃半截行容错、redact 钩子恒过一遍（契约 §10）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pddcheck.storage.atomic import atomic_write_text


@dataclass(frozen=True, slots=True)
class RunEvent:
    seq: int
    run_id: str
    phase: str                       # precheck/wake/launch/step/verify/commit/notify…
    event_name: str                  # capture_done / ocr_done / action_intent / …
    status: str                      # ok / failed / unknown …
    wall_time: str                   # RFC3339（展示用；预算用 monotonic）
    monotonic_ns: int
    duration_ns: int | None = None
    capture_id: str | None = None
    reading_ref: str | None = None
    action_id: str | None = None
    details: dict = field(default_factory=dict)


def _default_redact(details: dict) -> dict:
    """内置脱敏：任何看起来像端点/token 的键值都替换（调用方可再叠自己的钩子）。"""
    risky = ("url", "token", "key", "endpoint", "secret")
    out = {}
    for k, v in details.items():
        if any(r in k.lower() for r in risky):
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


class EventLog:
    def __init__(self, path: Path, run_id: str, redact=None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self._redact = redact or _default_redact
        self._seq = self._recover_seq()

    def _recover_seq(self) -> int:
        """seq 从**完好**行恢复——崩溃半截行不算数（跳过但不占号）。"""
        highest = 0
        for raw in self._iter_lines():
            try:
                obj = json.loads(raw)
                highest = max(highest, int(obj.get("seq", 0)))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return highest

    def append(self, event: RunEvent) -> int:
        seq = self._seq + 1
        row = {"seq": seq, "run_id": self.run_id, "phase": event.phase,
               "event_name": event.event_name, "status": event.status,
               "wall_time": event.wall_time, "monotonic_ns": event.monotonic_ns,
               "duration_ns": event.duration_ns,
               "capture_id": event.capture_id, "reading_ref": event.reading_ref,
               "action_id": event.action_id,
               "details": self._redact(dict(event.details))}
        # 崩溃残留的半截行没有结尾换行，会粘住下一条记录——先补 \n 再追加
        needs_newline = False
        if self.path.exists() and self.path.stat().st_size > 0:
            with open(self.path, "rb") as fh:
                fh.seek(-1, 2)
                needs_newline = fh.read(1) != b"\n"
        with open(self.path, "ab") as fh:
            if needs_newline:
                fh.write(b"\n")
            fh.write(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n")
            fh.flush()
            import os
            os.fsync(fh.fileno())
        self._seq = seq
        return seq

    def read_all(self) -> tuple[dict, ...]:
        rows = []
        for line_no, raw in enumerate(self._iter_lines(), 1):
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError:
                continue            # 崩溃半截行：跳过
        return tuple(rows)

    def _iter_lines(self):
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            yield from fh


def write_head(path: Path, payload: dict) -> None:
    """run manifest（run_id/版本/哈希）——原子写，与 events.jsonl 同目录。"""
    atomic_write_text(Path(path) / "manifest.json",
                      json.dumps(payload, ensure_ascii=False, indent=1))
