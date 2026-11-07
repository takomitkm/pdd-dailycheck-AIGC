"""T09：证据层测试——内容寻址/幂等/冲突拒绝、事件 seq 单调/半截行容错/内置脱敏。"""

from __future__ import annotations

import pytest

from pddcheck.evidence import (
    ArtifactCollision,
    ArtifactStore,
    EventLog,
    RunEvent,
)
from pddcheck.evidence.events import write_head


# --------------------------------------------------------------- 工件


def test_put_is_content_addressed_and_idempotent(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    ref1 = store.put(b"hello", "txt")
    ref2 = store.put(b"hello", "txt")
    assert ref1 == ref2
    assert ref1.rel_path.startswith(ref1.sha256[:2])
    assert store.open_bytes(ref1) == b"hello"


def test_put_different_content_collision(tmp_path):
    store = ArtifactStore(tmp_path / "a")
    store.put(b"one", "txt")
    # 同 sha 不可能不同内容——冲突场景用伪造路径验证：手改文件后重放
    ref = store.put(b"two", "txt")
    target = store.root / ref.rel_path
    target.write_bytes(b"tampered")
    with pytest.raises(ArtifactCollision):
        store.put(b"two", "txt")


def test_put_different_codec_same_content_gets_own_path(tmp_path):
    store = ArtifactStore(tmp_path / "a")
    r1 = store.put(b"x", "txt")
    r2 = store.put(b"x", "bin")
    assert r1.rel_path != r2.rel_path


# --------------------------------------------------------------- 事件流


def _event(seq_ignored, name="step_done", phase="step", status="ok", **details):
    return RunEvent(seq=0, run_id="run-1", phase=phase, event_name=name,
                    status=status, wall_time="2026-11-07T08:00:00+08:00",
                    monotonic_ns=1000, details=details)


def test_events_seq_monotonic_and_roundtrip(tmp_path):
    log = EventLog(tmp_path / "run" / "events.jsonl", "run-1")
    log.append(_event(0, "a"))
    log.append(_event(0, "b"))
    rows = log.read_all()
    assert [r["seq"] for r in rows] == [1, 2]
    assert [r["event_name"] for r in rows] == ["a", "b"]


def test_events_tolerate_crash_truncated_line(tmp_path):
    log = EventLog(tmp_path / "e.jsonl", "run-1")
    log.append(_event(0, "a"))
    with open(log.path, "a", encoding="utf-8") as fh:
        fh.write('{"seq":2,"event')                # 崩溃残留
    log2 = EventLog(tmp_path / "e.jsonl", "run-1")  # 重开：seq 从完好行数起
    assert log2.append(_event(0, "c")) == 2
    rows = log2.read_all()
    assert [r["event_name"] for r in rows] == ["a", "c"]


def test_events_builtin_redaction(tmp_path):
    log = EventLog(tmp_path / "e.jsonl", "run-1")
    log.append(_event(0, "push", push_url="https://sctapi/SECRET.send", taps=3))
    row = log.read_all()[0]
    assert row["details"]["push_url"] == "<redacted>"
    assert row["details"]["taps"] == 3


def test_manifest_atomic_head(tmp_path):
    write_head(tmp_path, {"run_id": "run-1", "source_sha256": "abc"})
    data = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert '"run_id": "run-1"' in data
