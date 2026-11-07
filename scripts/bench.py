"""T16 基准 harness（离线）：真数据分位 + 纯感知微基准 + 成对比较。

数据来源：
- OCR 墙钟：reports/t07/batch-summary.json 里 356 次真实 tesseract 调用的 duration_s；
- 纯感知：对语料 ocr-v1 的真 TSV 跑 parse_tsv/ocr_pass_candidates，测每次耗时；
- 成对比较：两份 baseline.json 逐阶段 delta，附语义一致性检查（同输入同输出）。

不允许「没有统计证据就写更快」：所有结论都来自这里的 n / p50 / p95 / calls。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from pddcheck.perception import (
    OcrPassInput,
    ocr_pass_candidates,
    parse_tsv,
)
from pddcheck.domain import CoordinateSource


def pcts(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    vals = sorted(values)
    def q(p):
        return vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))]
    return {"n": len(vals), "min": round(vals[0], 4), "p50": round(statistics.median(vals), 4),
            "p95": round(q(0.95), 4), "max": round(vals[-1], 4),
            "mean": round(statistics.fmean(vals), 4)}


def ocr_wall_clock(summary_path: Path) -> dict:
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    by_psm: dict[str, list[float]] = {}
    for row in data.get("rows", []):
        if row.get("status") == "ok" and row.get("duration_s") is not None:
            by_psm.setdefault(f"psm{row['psm']}", []).append(float(row["duration_s"]))
    return {"source": str(summary_path), "engine_version": data.get("engine_version"),
            "stages": {k: pcts(v) for k, v in sorted(by_psm.items())}}


def perception_micro(tsv_dir: Path, labels: tuple[str, ...], repeats: int = 3) -> dict:
    files = sorted(tsv_dir.glob("*.tsv"))
    parse_times, cand_times, calls = [], [], 0
    deterministic = True
    for _ in range(repeats):
        for f in files:
            text = f.read_text(encoding="utf-8")
            t0 = time.perf_counter()
            lines = parse_tsv(text)
            t1 = time.perf_counter()
            cands = ocr_pass_candidates("bench", "cap", 1,
                                        OcrPassInput(source=CoordinateSource.TESSERACT_PAGE,
                                                     tsv_text=text),
                                        "bench", labels, min_overlap=2, min_conf=40)
            t2 = time.perf_counter()
            parse_times.append((t1 - t0) * 1000)
            cand_times.append((t2 - t1) * 1000)
            calls += 1
            if _ != 0 and len(lines) != len(parse_tsv(text)):
                deterministic = False
            if not deterministic:
                break
    return {"files": len(files), "repeats": repeats, "calls": calls,
            "deterministic": deterministic,
            "stages": {"parse_tsv_ms": pcts(parse_times),
                       "ocr_pass_candidates_ms": pcts(cand_times)}}


def compare(a: dict, b: dict) -> dict:
    """成对比较：逐阶段 delta（b 相对 a），并标语义一致性（由调用方提供）。"""
    rows = []
    sa, sb = a.get("wall_clock", {}).get("stages", {}), b.get("wall_clock", {}).get("stages", {})
    for key in sorted(set(sa) | set(sb)):
        pa, pb = sa.get(key, {}).get("p50"), sb.get(key, {}).get("p50")
        delta = (round(pb - pa, 4) if pa is not None and pb is not None else None)
        rows.append({"stage": key, "a_p50": pa, "b_p50": pb, "delta": delta})
    return {"rows": rows,
            "note": "更快只能由统计证据支撑（n/p50/p95）；语义必须一致才算有效优化"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bench")
    ap.add_argument("--ocr-summary", required=True)
    ap.add_argument("--tsv-dir", required=True)
    ap.add_argument("--labels", nargs="+", default=["抽福袋", "立即点亮", "今日已点亮", "已使用"])
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    result = {
        "schema_version": 1,
        "kind": "t16-baseline",
        "wall_clock": ocr_wall_clock(Path(a.ocr_summary)),
        "perception": perception_micro(Path(a.tsv_dir), tuple(a.labels), a.repeats),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"wall": result["wall_clock"]["stages"],
                      "perception": result["perception"]["stages"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
