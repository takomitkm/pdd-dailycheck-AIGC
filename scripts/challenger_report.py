"""T07.4 挑战者合并报告：同一批帧上对齐 tesseract（既有原生测量）与 rapidocr（实测）。

tesseract 侧数据来源：reports/t07/batch-summary.json（原生 WSL 内测量，p50 分位）
+ ocr-v1 的 psm6 TSV（文本质量）。rapidocr 侧来自 reports/t16/rapidocr-challenger.json
的 rapidocr 段（本次实测）。两侧都用 perception 同口径算标签命中。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pddcheck.perception import longest_common_span, normalize  # noqa: E402

LABELS = ("抽福袋", "立即点亮", "今日已点亮", "已使用", "百亿补贴",
          "立即兑换", "待兑换", "下单", "抵扣")


def hits(text: str) -> int:
    clean = normalize(text)
    return sum(1 for lb in LABELS if longest_common_span(clean, normalize(lb))[0] >= 2)


def tsv_texts(tsv_dir: Path, stems: set[str]) -> list[str]:
    out = []
    for p in sorted(tsv_dir.glob("*.psm6.*.tsv")):
        stem = p.name.split(".psm6.")[0]
        if stem in stems:
            lines = p.read_text(encoding="utf-8").splitlines()
            words = []
            for ln in lines:
                cols = ln.split("\t")
                if len(cols) >= 12 and cols[0] == "5" and cols[11].strip() not in ("", "-"):
                    words.append(cols[11].strip())
            out.append(" ".join(words))
    return out


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    summary_path, tsv_dir = Path(argv[0]), Path(argv[1])
    challenger_path, frames_root = Path(argv[2]), Path(argv[3])
    out_path = Path(argv[4])

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    frames = sorted(frames_root.rglob("*.png"))[:12]
    stems = {p.stem for p in frames}

    # tesseract 侧：同 12 帧的 psm6 原生耗时 + TSV 质量
    durations = [r["duration_s"] for r in summary["rows"]
                 if r.get("status") == "ok" and r.get("psm") == 6
                 and Path(r["frame"]).stem in stems]
    texts = tsv_texts(tsv_dir, stems)
    tess = {
        "latency_s": {"n": len(durations),
                      "p50": round(sorted(durations)[len(durations) // 2], 3) if durations else None},
        "label_hits_total": sum(hits(t) for t in texts),
        "text_chars_total": sum(len(normalize(t)) for t in texts),
        "source": "reports/t07 原生测量 + ocr-v1 psm6 TSV",
    }

    chall = json.loads(challenger_path.read_text(encoding="utf-8"))
    rapid = chall["engines"].get("rapidocr", {})

    report = {
        "schema_version": 1,
        "kind": "ocr-challenger-merged",
        "frames": 12,
        "tesseract": tess,
        "rapidocr": rapid,
        "comparison": {
            "latency_ratio_rapid_over_tess": (
                round(rapid.get("latency_s", {}).get("p50", 0) / tess["latency_s"]["p50"], 2)
                if tess["latency_s"]["p50"] else None),
            "hit_ratio_rapid_over_tess": (
                round(rapid.get("label_hits_total", 0) / tess["label_hits_total"], 2)
                if tess["label_hits_total"] else None),
            "note": "两引擎在同一 12 帧上；质量命中同口径（normalize+连续段≥2）",
        },
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["comparison"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
