"""回放内核（T13）：加载运行证据、exact/trace 重演、跨运行差异。

所有输入来自已落盘的证据目录，不触设备。判定复用 workflow 判定核（同一语义）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pddcheck.workflow.verify import (
    ProofKind,
    VerifyObservation,
    VerifyStage,
    verify_light_decision,
)


class ReplayMode(StrEnum):
    EXACT = "exact"           # 复用记录的 OCR，不重跑
    REPROCESS = "reprocess"   # 重识别（由调用方注入新识别器），标原/新
    TRACE = "trace"           # 按序驱动状态机核对


class ReplayStatus(StrEnum):
    OK = "ok"
    INCOMPLETE = "incomplete"      # 缺 OCR/关键帧
    MISMATCH = "mismatch"          # trace 推演与记录不符


@dataclass(frozen=True, slots=True)
class RunTrace:
    run_dir: Path
    manifest: dict
    events: tuple[dict, ...]
    artifact_index: dict[str, Path]
    missing: tuple[str, ...] = field(default=())

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass(frozen=True, slots=True)
class ReplayResult:
    status: ReplayStatus
    mode: ReplayMode
    derived_lit: int | None = None
    derived_rc: int | None = None
    proof_kind: str = ProofKind.NONE.value
    why: str = ""
    incompleteness: tuple[str, ...] = ()
    reprocessed: tuple[dict, ...] = ()


def load_run(run_dir: Path) -> RunTrace:
    """从证据目录加载 manifest/events/工件索引。"""
    run_dir = Path(run_dir)
    manifest = {}
    mpath = run_dir / "manifest.json"
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    events = []
    epath = run_dir / "events.jsonl"
    if epath.exists():
        for raw in epath.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    index: dict[str, Path] = {}
    for p in sorted(run_dir.rglob("*")):
        if p.is_file() and p.name not in ("manifest.json", "events.jsonl"):
            index[p.relative_to(run_dir).as_posix()] = p
    missing = []
    if not mpath.exists():
        missing.append("manifest.json")
    if not epath.exists():
        missing.append("events.jsonl")
    if not any(p.suffix == ".tsv" for p in index.values()):
        missing.append("ocr_tsv")
    return RunTrace(run_dir, manifest, tuple(events), index, tuple(missing))


def _obs_from_events(events: tuple[dict, ...]) -> tuple[int | None, str, tuple[VerifyObservation, ...]]:
    """把记录里的 verify 观察序列还原成判定核输入（stage/after/done/prize/pend）。"""
    before = None
    method = "ocr"
    obs: list[VerifyObservation] = []
    for e in events:
        name = e.get("event_name")
        d = e.get("details", {})
        if name == "check_before":
            before = d.get("before_count", before)
        if name == "tap":
            method = d.get("tap_method", method)
        if name == "verify_observation":
            obs.append(VerifyObservation(
                stage=VerifyStage(d["stage"]),
                after_count=d.get("after_count"),
                done_text=bool(d.get("done_text", False)),
                prize_text=bool(d.get("prize_text", False)),
                pend_text=bool(d.get("pend_text", False)),
                reenter_failed=bool(d.get("reenter_failed", False)),
            ))
    return before, method, tuple(obs)


def exact_replay(trace: RunTrace) -> ReplayResult:
    """exact：不重识别，仅按记录观察重演判定。缺料 → INCOMPLETE。"""
    if not trace.complete:
        return ReplayResult(ReplayStatus.INCOMPLETE, ReplayMode.EXACT,
                            incompleteness=trace.missing)
    before, method, obs = _obs_from_events(trace.events)
    if not obs:
        return ReplayResult(ReplayStatus.INCOMPLETE, ReplayMode.EXACT,
                            incompleteness=("verify_observation",))
    out = verify_light_decision(before, method, obs)
    return ReplayResult(ReplayStatus.OK, ReplayMode.EXACT, out.lit, out.rc,
                        out.proof_kind.value, out.why)


def trace_replay(trace: RunTrace) -> ReplayResult:
    """trace：重演推导并与记录里的 outcome 比对，不一致 → MISMATCH。"""
    base = exact_replay(trace)
    if base.status is not ReplayStatus.OK:
        return ReplayResult(base.status, ReplayMode.TRACE,
                            incompleteness=base.incompleteness)
    recorded_lit = None
    for e in trace.events:
        if e.get("event_name") == "outcome":
            recorded_lit = e.get("details", {}).get("lit")
    status = ReplayStatus.OK if recorded_lit in (None, base.derived_lit) else ReplayStatus.MISMATCH
    return ReplayResult(status, ReplayMode.TRACE, base.derived_lit, base.derived_rc,
                        base.proof_kind, base.why)


def diff_runs(a: RunTrace, b: RunTrace) -> dict:
    """两次运行的差异；缺时间戳时标对齐不确定性，绝不按最近文件名伪造同一采样时刻。"""
    def digest(t: RunTrace) -> dict:
        return {
            "run_id": t.manifest.get("run_id"),
            "source_sha256": t.manifest.get("source_sha256"),
            "has_wall_clock": any(e.get("wall_time") for e in t.events),
            "artifacts": sorted(t.artifact_index),
        }
    da, db = digest(a), digest(b)
    uncertainty = []
    if not da["has_wall_clock"] or not db["has_wall_clock"]:
        uncertainty.append("缺少墙钟时间戳：两次运行无法证明同一采样时刻")
    return {"a": da, "b": db,
            "artifacts_only_in_a": sorted(set(da["artifacts"]) - set(db["artifacts"])),
            "artifacts_only_in_b": sorted(set(db["artifacts"]) - set(da["artifacts"])),
            "alignment_uncertainty": uncertainty}
