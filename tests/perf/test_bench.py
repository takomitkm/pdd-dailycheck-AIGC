"""T16：基准 harness 自测——分位数、调用计数、确定性、成对比较、schema。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import bench  # noqa: E402

TSV = "5\t1\t1\t1\t1\t1\t100\t880\t30\t40\t92\t抽福袋\n" \
      "5\t1\t2\t1\t2\t1\t100\t900\t40\t20\t88\t立即点亮\n"


def test_pcts_basic():
    s = bench.pcts([1.0, 2.0, 3.0, 4.0])
    assert s["n"] == 4 and s["p50"] == 2.5 and s["max"] == 4.0


def test_perception_micro_counts_and_determinism(tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.tsv").write_text(TSV, encoding="utf-8")
    res = bench.perception_micro(tmp_path, ("抽福袋", "立即点亮"), repeats=2)
    assert res["files"] == 3 and res["calls"] == 6          # 3 文件 × 2 轮
    assert res["deterministic"] is True
    assert res["stages"]["parse_tsv_ms"]["n"] == 6
    assert "p95" in res["stages"]["ocr_pass_candidates_ms"]


def test_ocr_wall_clock_from_summary(tmp_path):
    summary = {"engine_version": "tesseract 5.5.0",
               "rows": [{"psm": 11, "status": "ok", "duration_s": 1.0},
                        {"psm": 11, "status": "ok", "duration_s": 1.4},
                        {"psm": 6, "status": "ok", "duration_s": 0.5},
                        {"psm": 11, "status": "timeout", "duration_s": 30.0}]}
    p = tmp_path / "s.json"
    p.write_text(json.dumps(summary), encoding="utf-8")
    out = bench.ocr_wall_clock(p)
    assert out["engine_version"] == "tesseract 5.5.0"
    assert out["stages"]["psm11"]["n"] == 2                 # 只统计 ok
    assert out["stages"]["psm6"]["p50"] == 0.5


def test_compare_reports_delta():
    a = {"wall_clock": {"stages": {"psm11": {"p50": 1.2}}}}
    b = {"wall_clock": {"stages": {"psm11": {"p50": 0.9}}}}
    out = bench.compare(a, b)
    row = next(r for r in out["rows"] if r["stage"] == "psm11")
    assert row["delta"] == -0.3 and "统计证据" in out["note"]


def test_main_writes_schema(tmp_path):
    summary = tmp_path / "s.json"
    summary.write_text(json.dumps({"engine_version": "t", "rows": [
        {"psm": 11, "status": "ok", "duration_s": 1.1}]}), encoding="utf-8")
    tsv_dir = tmp_path / "tsvs"
    tsv_dir.mkdir()
    (tsv_dir / "a.tsv").write_text(TSV, encoding="utf-8")
    out = tmp_path / "baseline.json"
    assert bench.main(["--ocr-summary", str(summary), "--tsv-dir", str(tsv_dir),
                       "--repeats", "1", "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["kind"] == "t16-baseline"
    assert data["perception"]["calls"] == 1
    assert data["wall_clock"]["stages"]["psm11"]["n"] == 1
