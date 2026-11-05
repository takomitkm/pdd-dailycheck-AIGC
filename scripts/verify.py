#!/usr/bin/env python
"""门禁入口雏形（tasks.md T02；完整 G0 终验待 T00/T01 交付后接入）。

用法::

    python scripts/verify.py [--gate NAME] [--output DIR]

- 跑 tests/ 下的 pytest，机器可读结果写 <output>/verify-result.json；
- pytest 不可用属基础设施错误，exit 3，绝不假装绿（acceptance.md §10）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="pddcheck 门禁入口")
    parser.add_argument("--gate", default="G0-skeleton")
    parser.add_argument("--output", default=str(ROOT / "reports"))
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    try:
        import pytest
    except ImportError:
        result = {
            "gate": args.gate,
            "status": "infra_error",
            "exit_code": 3,
            "reason": "pytest 未安装；用 uv/pip 装 dev 组依赖后重试，不要跳过测试",
            "python": sys.version.split()[0],
        }
        _write(out_dir, result)
        print(json.dumps(result, ensure_ascii=False))
        return 3

    code = pytest.main(["-q", str(ROOT / "tests"), "-p", "no:cacheprovider"])
    result = {
        "gate": args.gate,
        "status": "passed" if code == 0 else "failed",
        "exit_code": int(code),
        "duration_s": round(time.time() - started, 3),
        "python": sys.version.split()[0],
    }
    _write(out_dir, result)
    print(json.dumps(result, ensure_ascii=False))
    return int(code)


def _write(out_dir: Path, result: dict) -> None:
    path = out_dir / "verify-result.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
