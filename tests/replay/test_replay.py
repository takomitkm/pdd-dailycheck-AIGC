"""T13：回放与静态报告测试——exact/trace/INCOMPLETE/差异不确定性/零远端资源。"""

from __future__ import annotations

import json

from pddcheck.replay import (
    ReplayMode,
    ReplayStatus,
    diff_runs,
    exact_replay,
    load_run,
    render_report,
    trace_replay,
)


def make_run(tmp_path, *, with_tsv=True, with_events=True, before=4, after=3,
             method="ocr", outcome_lit=3, wall="2026-11-07T10:00:00+08:00"):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": "run-1", "source_sha256": "abc"}), encoding="utf-8")
    events = []
    if with_events:
        events = [
            {"seq": 1, "phase": "step", "event_name": "check_before", "status": "ok",
             "wall_time": wall, "duration_ns": 5_000_000,
             "details": {"before_count": before}},
            {"seq": 2, "phase": "step", "event_name": "tap", "status": "ok",
             "wall_time": wall, "details": {"tap_method": method}},
            {"seq": 3, "phase": "verify", "event_name": "verify_observation", "status": "ok",
             "wall_time": wall, "duration_ns": 8_000_000,
             "details": {"stage": "after_direct", "after_count": after}},
            {"seq": 4, "phase": "commit", "event_name": "outcome", "status": "ok",
             "wall_time": wall, "details": {"lit": outcome_lit}},
        ]
        (run_dir / "events.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
            encoding="utf-8")
    if with_tsv:
        (run_dir / "ocr").mkdir(exist_ok=True)
        (run_dir / "ocr" / "frame.psm11.tsv").write_text(
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t92\t抽福袋\n", encoding="utf-8")
    return run_dir


def test_exact_replay_derives_counter_decrease(tmp_path):
    trace = load_run(make_run(tmp_path))
    assert trace.complete
    res = exact_replay(trace)
    assert res.status is ReplayStatus.OK and res.derived_lit == 3 and res.derived_rc == 0
    assert res.proof_kind == "counter_decrease"


def test_exact_replay_unchanged_counter_is_rc6(tmp_path):
    trace = load_run(make_run(tmp_path, after=4))
    res = exact_replay(trace)
    assert res.derived_rc == 1 and res.derived_lit is None


def test_missing_ocr_is_incomplete_without_faking(tmp_path):
    trace = load_run(make_run(tmp_path, with_tsv=False))
    assert not trace.complete and "ocr_tsv" in trace.missing
    res = exact_replay(trace)
    assert res.status is ReplayStatus.INCOMPLETE
    assert "ocr_tsv" in res.incompleteness


def test_missing_events_is_incomplete(tmp_path):
    trace = load_run(make_run(tmp_path, with_events=False))
    res = exact_replay(trace)
    assert res.status is ReplayStatus.INCOMPLETE
    assert "events.jsonl" in res.incompleteness


def test_trace_replay_mismatch_when_recorded_outcome_differs(tmp_path):
    trace = load_run(make_run(tmp_path, before=4, after=3, outcome_lit=1))  # 记录说 lit1，推演 lit3
    res = trace_replay(trace)
    assert res.status is ReplayStatus.MISMATCH


def test_trace_replay_ok_when_consistent(tmp_path):
    trace = load_run(make_run(tmp_path, before=4, after=3, outcome_lit=3))
    res = trace_replay(trace)
    assert res.status is ReplayStatus.OK and res.derived_lit == 3


def test_diff_marks_alignment_uncertainty_without_wall_clock(tmp_path):
    a = load_run(make_run(tmp_path / "a", wall=None))
    b = load_run(make_run(tmp_path / "b", wall=None))
    d = diff_runs(a, b)
    assert any("同一采样时刻" in u for u in d["alignment_uncertainty"])


def test_diff_with_wall_clock_has_no_uncertainty(tmp_path):
    a = load_run(make_run(tmp_path / "a"))
    b = load_run(make_run(tmp_path / "b"))
    assert diff_runs(a, b)["alignment_uncertainty"] == []


def test_report_is_self_contained_no_remote_resources(tmp_path):
    trace = load_run(make_run(tmp_path))
    html = render_report(trace, exact_replay(trace))
    low = html.lower()
    assert "http://" not in low and "https://" not in low
    assert "<script" not in low
    assert "抽福袋" not in html                  # 报告不泄漏屏幕原文（工件名可列，内容不入）
    assert "counter_decrease" in html


def test_report_escapes_injected_text(tmp_path):
    run_dir = make_run(tmp_path)
    # 注入恶意 event 名，验证转义
    with open(run_dir / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"seq": 9, "phase": "<img src=x onerror=alert(1)>",
                             "event_name": "x", "status": "ok",
                             "wall_time": "2026-11-07T10:00:00+08:00"}) + "\n")
    trace = load_run(run_dir)
    html = render_report(trace, exact_replay(trace))
    # 尖括号必须转义（危险标签失效）；纯文本片段保留可读，不算未转义
    assert "<img src=x" not in html and "&lt;img src=x" in html
