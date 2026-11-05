#!/usr/bin/env python
"""T04：把私有真图语料（仓库外）建立可入库的索引清单。

用法::

    python tests/fixtures/manifest/build_corpus_index.py \
        --corpus S:/apps/llm/agentwork/pdd-corpus-private/pdd-runs \
        --out tests/fixtures/manifest/corpus-v1-index.json

只输出：相对路径、SHA256、字节数、会话（日期/场次）、帧类别（从证据文件名解析，
如 100233-bag-1.png → key=bag）。**任何像素、OCR 文本、昵称都不进索引**。
原图哈希足以在私有目录里定位文件；私有目录一旦挪动/脱敏，索引需重跑。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

FRAME_KEY = re.compile(r"^\d{6}-(?P<key>[a-z]+)-?\d*\.png$", re.I)
KNOWN_KEYS = ("bag", "light", "browse", "pend", "done", "popup", "prove", "count", "take", "shot")


def classify(rel: str) -> str:
    name = Path(rel).name
    m = FRAME_KEY.match(name)
    if m:
        key = m.group("key")
        return key if key in KNOWN_KEYS else "png-other"
    if name.endswith(".png"):
        return "png-other"
    if name.endswith(".xml"):
        return "hierarchy-xml"
    if name == "run.log":
        return "run-log"
    if name == "summary.txt":
        return "summary"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.corpus)
    if not root.is_dir():
        raise SystemExit(f"语料目录不存在：{root}")
    files = []
    counts: Counter[str] = Counter()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        cls = classify(rel)
        counts[cls] += 1
        parts = rel.split("/")
        session = f"{parts[0]}/{parts[1]}" if len(parts) >= 3 else ""
        files.append({
            "path": rel,
            "sha256": digest,
            "bytes": p.stat().st_size,
            "session": session,
            "class": cls,
        })
    sessions = sorted({f["session"] for f in files if f["session"]})
    payload = {
        "schema_version": 1,
        "kind": "corpus-index",
        "privacy": "索引只含路径/哈希/尺寸/类别；原图含昵称与券面额，只存于仓库外私有目录",
        "corpus_root": str(root),
        "source": "deb-h61 ~/Desktop/pdd-runs 7 天窗（2026-11-06 07:45 回收）+ 真机只读截图 ×2",
        "total_files": len(files),
        "sessions": sessions,
        "class_counts": dict(sorted(counts.items())),
        "files": files,
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"files": len(files), "sessions": len(sessions),
                      "classes": dict(sorted(counts.items()))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
