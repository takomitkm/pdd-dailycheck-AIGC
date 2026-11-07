"""T08：存储层测试——原子写/运行锁/日标记/账本兼容/journal 未决恢复。

运行锁是 POSIX（fcntl）语义：Windows smoke 环境跳过（生产目标 Debian）。
"""

from __future__ import annotations

import sys

import pytest

from pddcheck.storage import (
    DailyStore,
    Journal,
    atomic_write_text,
)

posix_only = pytest.mark.skipif(sys.platform == "win32",
                                reason="运行锁是 POSIX（fcntl）语义，生产目标 Debian")

if sys.platform != "win32":
    from pddcheck.storage import LockBusy, acquire_run_lease


# --------------------------------------------------------------- 原子写


def test_atomic_write_roundtrip_and_overwrite(tmp_path):
    target = tmp_path / "state" / "marker"
    atomic_write_text(target, "v1")
    assert target.read_text(encoding="utf-8") == "v1"
    atomic_write_text(target, "v2")
    assert target.read_text(encoding="utf-8") == "v2"
    # 目录里不留 temp 残渣
    assert [p.name for p in target.parent.iterdir()] == [target.name]


def test_atomic_write_leaves_old_content_on_failure(tmp_path):
    target = tmp_path / "f"
    atomic_write_text(target, "old")
    blocker = tmp_path / "sub"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        atomic_write_text(blocker / "f", "new")    # 目录路径被文件占住 → mkdir 失败
    assert target.read_text(encoding="utf-8") == "old"


# --------------------------------------------------------------- 运行锁（POSIX）


@posix_only
def test_lease_exclusive_second_instance_fails_fast(tmp_path):
    lock = tmp_path / "locks" / "device.lock"
    with acquire_run_lease(lock, "dev-1"):
        with pytest.raises(LockBusy):
            acquire_run_lease(lock, "dev-1")
    with acquire_run_lease(lock, "dev-1"):
        pass


@posix_only
def test_lease_release_is_idempotent(tmp_path):
    lease = acquire_run_lease(tmp_path / "l.lock", "dev-1")
    lease.release()
    lease.release()  # 不抛
    with acquire_run_lease(tmp_path / "l.lock", "dev-1"):
        pass


@posix_only
def test_lease_threads_are_mutually_exclusive(tmp_path):
    import threading
    lock = tmp_path / "l.lock"
    acquired_second = []

    def second():
        try:
            acquire_run_lease(lock, "dev-1")
            acquired_second.append(True)
        except LockBusy:
            pass

    with acquire_run_lease(lock, "dev-1"):
        t = threading.Thread(target=second)
        t.start()
        t.join()
    assert acquired_second == []


# --------------------------------------------------------------- 日标记与账本


def test_marker_write_and_exists(tmp_path):
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    assert not store.marker_exists("2026-11-07")
    store.write_marker("2026-11-07")
    assert store.marker_exists("2026-11-07")
    assert store.marker_path("2026-11-07").name == ".done-2026-11-07"   # 兼容旧路径形状


def test_ledger_garbage_and_missing_never_block(tmp_path):
    # case40/41 口径：垃圾字符、文件不存在都不挡路（读作 None）
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    assert store.ledger_read() is None                    # 不存在
    store.ledger_path.write_text("abc\n", encoding="utf-8")
    assert store.ledger_read() is None                    # 垃圾
    store.ledger_path.write_text("", encoding="utf-8")
    assert store.ledger_read() is None                    # 空


def test_ledger_write_read_roundtrip(tmp_path):
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    assert store.ledger_write(3) and store.ledger_read() == 3
    assert store.ledger_clear() and store.ledger_read() == 0   # case39/42：清 0


# --------------------------------------------------------------- journal


def test_journal_intent_receipt_flow(tmp_path):
    j = Journal(tmp_path / "journal" / "actions.jsonl")
    j.record_intent("a1", "tap", {"target": "light", "state_epoch": 3})
    j.record_receipt("a1", "acknowledged", None)
    j.record_intent("a2", "tap", {"target": "light", "state_epoch": 4})
    entries = j.entries()
    assert [e.kind for e in entries] == ["intent", "receipt", "intent"]
    unresolved = j.unresolved_intents()
    assert len(unresolved) == 1 and unresolved[0].payload["action_id"] == "a2"


def test_journal_tolerates_truncated_tail(tmp_path):
    j = Journal(tmp_path / "j.jsonl")
    j.record_intent("a1", "tap", {})
    with open(j.path, "a", encoding="utf-8") as fh:
        fh.write('{"seq":2,"kind":"int')       # 崩溃残留的半截行
    entries = j.entries()
    assert len(entries) == 1 and entries[0].payload["action_id"] == "a1"
    e = j.record_intent("a2", "tap", {})       # 半截行之后仍能追加且 seq 不撞
    assert e.seq == 3


def test_journal_empty_when_absent(tmp_path):
    assert Journal(tmp_path / "none.jsonl").entries() == ()
