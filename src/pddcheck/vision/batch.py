"""真图语料的整页 OCR 批处理（T07/T04）：对私有语料的整页帧跑 psm11/psm6，
raw TSV 落私有 ocr 工件目录，索引汇总落仓库（不含像素/识别内容的敏感面——
TSV 里会有屏幕原文，**只进私有目录**；仓库只落 per-frame 的耗时/状态汇总）。

用法（WSL 内，tesseract 5.x 可用）::

    PYTHONPATH=src python3 -m pddcheck.vision.batch \
        --corpus /mnt/s/apps/llm/agentwork/pdd-corpus-private/pdd-runs \
        --index tests/fixtures/manifest/corpus-v1-index.json \
        --out /mnt/s/apps/llm/agentwork/pdd-corpus-private/ocr-v1 \
        --summary reports/t07/batch-summary.json --psm 11 6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from pddcheck.domain import ReadStatus
from pddcheck.vision.tesseract import TesseractConfig, run_tesseract_tsv, tesseract_version


def _full_frames(index_path: Path, corpus: Path) -> list[tuple[str, Path]]:
    """索引里 class ∈ {bag,popup,pend,done,browse,light,shot,png-other 中带整页形状的}
    ——判据：证据名形如 <6位时刻>-<key>-<n>.png 或 shot.png 的整页帧；
    band/pill 裁片（文件名含 -band/-pill 或在 pill*/band* 前缀目录）跳过。"""
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    out: list[tuple[str, Path]] = []
    for f in payload["files"]:
        name = f["path"].rsplit("/", 1)[-1]
        if not name.endswith(".png") or f["class"] in ("hierarchy-xml",):
            continue
        stem = name[:-4]
        if "-band" in stem or "-pill" in stem or stem.startswith(("band", "pill")):
            continue
        if f["class"] == "png-other" and "-" not in stem:
            continue
        out.append((f["path"], corpus / f["path"]))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="整页 OCR 批处理（T07）")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--out", required=True, help="raw TSV 工件目录（私有）")
    ap.add_argument("--summary", required=True, help="仓库侧汇总 JSON（无敏感内容）")
    ap.add_argument("--psm", type=int, nargs="+", default=[11, 6])
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 帧（试跑用）")
    a = ap.parse_args(argv)

    corpus = Path(a.corpus)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = Path(a.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    version = tesseract_version()
    if version is None:
        print(json.dumps({"status": "infra_error", "reason": "tesseract 不可用"}))
        return 3
    cfg = TesseractConfig(timeout_s=a.timeout)

    frames = _full_frames(Path(a.index), corpus)
    if a.limit:
        frames = frames[: a.limit]
    rows = []
    for rel, png in frames:
        if not png.is_file():
            rows.append({"frame": rel, "status": "missing"})
            continue
        for psm in a.psm:
            t0 = time.monotonic()
            res = run_tesseract_tsv(png, psm, cfg, engine_version=version)
            artifact = None
            if res.status is ReadStatus.OK:
                digest = hashlib.sha256(png.read_bytes()).hexdigest()[:12]
                artifact = f"{Path(rel).stem}.psm{psm}.{digest}.tsv"
                (out_dir / artifact).write_text(res.tsv_text, encoding="utf-8")
            rows.append({
                "frame": rel, "psm": psm, "status": str(res.status.value),
                "error": res.error_code, "rc": res.returncode,
                "duration_s": round(res.duration_s, 3), "artifact": artifact,
            })
            print(f"{rel} psm{psm} {res.status.value} {res.duration_s:.2f}s", flush=True)
    ok = sum(1 for r in rows if r.get("status") == "ok")
    summary = {
        "schema_version": 1,
        "kind": "ocr-batch-summary",
        "engine_version": version,
        "psm": a.psm,
        "frames": len(frames),
        "runs": len(rows),
        "ok": ok,
        "rows": rows,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"frames": len(frames), "runs": len(rows), "ok": ok}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
