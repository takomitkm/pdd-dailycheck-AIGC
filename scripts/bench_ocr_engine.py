"""OCR 引擎对比基准（T07.4）：tesseract vs rapidocr，对同一语料成对比较。

输出（per engine）：逐帧耗时分位、识别文本行数/字数、对已知标签的命中数
（用 perception 的 normalize+连续段匹配，与线上同口径）、失败分型。

判据：交替跑两台引擎在同一批帧上；质量按标签命中数、速度按 p50/p95；
结论只在两侧都有统计样本时给出（T16 与 T07.4 的共同要求）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pddcheck.perception import longest_common_span, normalize  # noqa: E402

LABELS = ("抽福袋", "立即点亮", "今日已点亮", "已使用", "百亿补贴",
          "立即兑换", "待兑换", "下单", "抵扣")


def _pcts(values):
    if not values:
        return {"n": 0}
    vals = sorted(values)
    def q(p):
        return vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))]
    return {"n": len(vals), "min": round(vals[0], 4), "p50": round(statistics.median(vals), 4),
            "p95": round(q(0.95), 4), "max": round(vals[-1], 4)}


def _label_hits(text: str) -> int:
    clean = normalize(text)
    return sum(1 for lb in LABELS if longest_common_span(clean, normalize(lb))[0] >= 2)


def _wsl_path(png: Path) -> str:
    """Windows 绝对路径 → WSL 路径（S:\\a\\b.png → /mnt/s/a/b.png）。"""
    p = str(png)
    drive = p[0].lower()
    rest = p[2:].replace("\\", "/").lstrip("/")
    return f"/mnt/{drive}/{rest}"


def run_tesseract(png: Path, psm: int = 6, timeout: float = 30.0) -> tuple[str, float, str | None]:
    t0 = time.perf_counter()
    try:
        cp = subprocess.run(["wsl.exe", "-e", "bash", "-lc",
                             f"tesseract '{_wsl_path(png)}' stdout "
                             f"-l chi_sim+eng --psm {psm} 2>/dev/null"],
                            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", timeout, "timeout"
    dt = time.perf_counter() - t0
    if cp.returncode != 0:
        return "", dt, f"rc_{cp.returncode}"
    return cp.stdout, dt, None


def run_rapidocr(engine, png: Path) -> tuple[str, float, str | None]:
    t0 = time.perf_counter()
    try:
        result, _ = engine(str(png))
    except Exception as exc:                       # 单帧失败不炸整批，留痕
        return "", time.perf_counter() - t0, f"err_{type(exc).__name__}"
    dt = time.perf_counter() - t0
    text = "\n".join(item[1] for item in result) if result else ""
    return text, dt, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bench_ocr_engine")
    ap.add_argument("--frames", required=True, help="帧目录（递归找 *.png）")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--engines", nargs="+", default=["tesseract", "rapidocr"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    frames = sorted(Path(a.frames).rglob("*.png"))[: a.limit]
    rapid = None
    if "rapidocr" in a.engines:
        try:
            from rapidocr_onnxruntime import RapidOCR
            rapid = RapidOCR()
        except Exception as exc:
            print(f"rapidocr 不可用：{type(exc).__name__}: {exc}", file=sys.stderr)
            a.engines = [e for e in a.engines if e != "rapidocr"]
    report = {"schema_version": 1, "kind": "ocr-engine-challenger",
              "frames": len(frames), "engines": {}}
    for engine_name in a.engines:
        times, hits, errs, chars = [], [], {}, []
        for png in frames:
            if engine_name == "tesseract":
                text, dt, err = run_tesseract(png)
            else:
                text, dt, err = run_rapidocr(rapid, png)
            times.append(round(dt, 3))
            if err:
                errs[err] = errs.get(err, 0) + 1
            hits.append(_label_hits(text))
            chars.append(len(normalize(text)))
        report["engines"][engine_name] = {
            "latency_s": _pcts(times), "label_hits_total": sum(hits),
            "text_chars_total": sum(chars), "errors": errs,
            "avg_hits_per_frame": round(sum(hits) / max(1, len(hits)), 2),
        }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["engines"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
