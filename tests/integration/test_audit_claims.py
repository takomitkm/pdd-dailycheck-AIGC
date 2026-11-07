"""T19 前置：交付完整性审计作为门禁——任何 FAIL 即红；证据缺失记 SKIP 可见。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_claims  # noqa: E402


def test_audit_has_no_failures():
    rc = audit_claims.main([])
    report = json.loads((ROOT / "reports" / "audit.json").read_text(encoding="utf-8"))
    fails = [r for r in report["results"] if r["status"] == "FAIL"]
    assert not fails, f"审计失败：{fails}"
    assert rc == 0


def test_audit_covers_key_claims():
    names = {n for n, _ in audit_claims.CLAIMS}
    for required in ("oracle47-coverage", "mutations-11", "g0-harness",
                     "t16-baseline", "t16-callcount", "required-files"):
        assert required in names
