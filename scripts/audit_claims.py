"""交付完整性自检：把 merge-report 里的关键断言对着仓库证据逐条核。

每条 claim 输出 PASS / FAIL / SKIP（证据缺失=SKIP，不算通过也不算失败，但在报告里
可见）。任何 FAIL → 退出码 1。目的是防止「报告写得好、实际漂移」。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def c_oracle():
    d = _load(REPORTS / "t15" / "oracle-coverage.json")
    if d is None:
        return "SKIP", "缺 reports/t15/oracle-coverage.json"
    total = d.get("flow_executed", 0) + d.get("kernel_executed", 0) + len(d.get("suite_covered", []))
    ok = d.get("total") == 47 and total == 47 and len(d.get("declared_ids", [])) >= 37
    return ("PASS", f"47={total}, declared={len(d.get('declared_ids', []))}") if ok else ("FAIL", str(d))


def c_mutations():
    d = _load(REPORTS / "t15" / "mutations.json")
    if d is None:
        return "SKIP", "缺 reports/t15/mutations.json"
    ok = d.get("executed") == 11 and d.get("killed") == 11 and d.get("survived") == 0 \
        and d.get("infra_errors") == 0 and len(d.get("mutants", [])) == 11
    return ("PASS", "11/11 killed, 0 survived") if ok else ("FAIL", str(d))


def c_g0():
    d = _load(REPORTS / "harness-result.json")
    if d is None:
        return "SKIP", "缺 reports/harness-result.json"
    runs = d.get("runs", [])
    ok = d.get("pass") is True and len(runs) == 2 and all(
        r.get("executed") == 47 and r.get("failed") == 0 and r.get("skipped") == 0 for r in runs)
    neg = d.get("negative_controls", [])
    ok = ok and len(neg) == 1 and neg[0].get("killed") == 11 and neg[0].get("survived") == 0
    cex = d.get("counterexamples", [])
    ok = ok and len(cex) == 4 and all(c.get("as_expected") for c in cex)
    return ("PASS", "runs=2×47, neg 11/11, cex 4") if ok else ("FAIL", f"runs={len(runs)} neg={neg} cex={len(cex)}")


def c_baseline():
    d = _load(ROOT / "docs" / "refactor-v2" / "t16-baseline.json")
    if d is None:
        return "SKIP", "缺 t16-baseline.json"
    st = d.get("wall_clock", {}).get("stages", {})
    ok = st.get("psm11", {}).get("n") == 178 and st.get("psm6", {}).get("n") == 178
    return ("PASS", "psm11/psm6 n=178") if ok else ("FAIL", str(st))


def c_callcount():
    d = _load(ROOT / "docs" / "refactor-v2" / "t16-callcount.json")
    if d is None:
        return "SKIP", "缺 t16-callcount.json"
    pf = d.get("per_frame", {})
    ok = pf.get("legacy", 0) == 69 and pf.get("shared", 0) == 9 and d.get("reduction_lazy_pct") == 87.0
    return ("PASS", "69→9, -87%") if ok else ("FAIL", str(pf))


def c_challenger():
    d = _load(ROOT / "docs" / "refactor-v2" / "t07-rapidocr-challenger.json")
    if d is None:
        return "SKIP", "缺 t07-rapidocr-challenger.json"
    cmp = d.get("comparison", {})
    ok = (cmp.get("latency_ratio_rapid_over_tess") or 0) > 1 and \
         (cmp.get("hit_ratio_rapid_over_tess") or 0) > 1
    return ("PASS", f"lat×{cmp.get('latency_ratio_rapid_over_tess')} hit×{cmp.get('hit_ratio_rapid_over_tess')}") \
        if ok else ("FAIL", str(cmp))


REQUIRED_FILES = [
    "src/pddcheck/domain/__init__.py", "src/pddcheck/config/profile.py",
    "src/pddcheck/perception/observe.py", "src/pddcheck/vision/engine.py",
    "src/pddcheck/workflow/flow.py", "src/pddcheck/storage/journal.py",
    "src/pddcheck/notify/sender.py", "src/pddcheck/evidence/events.py",
    "src/pddcheck/replay/trace.py", "src/pddcheck/device/adb.py",
    "src/pddcheck/cli/bootstrap.py", "src/pddcheck/cli/exits.py",
    "scripts/build_wheel.py", "scripts/release.py", "scripts/bench.py",
    "packaging/launcher.sh", "packaging/systemd/pddcheck.service.candidate",
    "docs/refactor-v2/merge-report.md",
]


def c_files():
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
    return ("PASS", f"{len(REQUIRED_FILES)} 文件齐") if not missing else ("FAIL", f"缺 {missing}")


def c_test_collect(threshold: int = 333) -> tuple[str, str]:
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
                            "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True,
                           timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "SKIP", f"收集失败：{exc}"
    import re
    # pytest 9 的 -q --collect-only 按文件输出 "tests/x.py: N"，没有总数行 → 累加
    counts = [int(m) for m in re.findall(r"^tests/\S+\.py:\s*(\d+)\s*$", p.stdout, re.M)]
    n = sum(counts) if counts else -1
    return ("PASS", f"collected={n} ≥ {threshold}") if n >= threshold else (
        "FAIL", f"collected={n}" if n >= 0 else p.stdout[-300:])


CLAIMS = [
    ("oracle47-coverage", c_oracle),
    ("mutations-11", c_mutations),
    ("g0-harness", c_g0),
    ("t16-baseline", c_baseline),
    ("t16-callcount", c_callcount),
    ("t07-challenger", c_challenger),
    ("required-files", c_files),
    ("tests-collected", c_test_collect),
]


def main(argv=None) -> int:
    results = []
    for name, fn in CLAIMS:
        status, detail = fn()
        results.append({"claim": name, "status": status, "detail": detail})
    fails = [r for r in results if r["status"] == "FAIL"]
    payload = {"schema_version": 1, "kind": "delivery-audit",
               "pass": not fails, "fails": len(fails),
               "results": results}
    (REPORTS).mkdir(exist_ok=True)
    (REPORTS / "audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    for r in results:
        print(f"{r['status']:4} {r['claim']}: {r['detail']}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
