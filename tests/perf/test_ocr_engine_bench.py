"""T07.4：引擎对比基准自测——标签命中口径、分位、假引擎端到端、报告 schema。"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import bench_ocr_engine as bench  # noqa: E402


def test_label_hits_uses_same_matching_as_online():
    assert bench._label_hits("抽福袋 立即点亮") >= 2
    assert bench._label_hits("无关文字") == 0
    assert bench._label_hits("立即 点 亮") >= 1          # 规范化后仍可命中


def test_pcts_shape():
    s = bench._pcts([0.5, 1.0, 2.0])
    assert s["n"] == 3 and s["max"] == 2.0 and "p95" in s


def test_main_with_fake_engine(tmp_path, monkeypatch, capsys):
    # 假 rapidocr 模块：返回 [(box, text, score), ...]
    fake = types.ModuleType("rapidocr_onnxruntime")
    class RapidOCR:
        def __call__(self, path):
            return ([([[0, 0], [1, 0], [1, 1], [0, 1]], "抽福袋 立即点亮", 0.9)], None)
    fake.RapidOCR = RapidOCR
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake)

    frames = tmp_path / "f"
    frames.mkdir()
    for i in range(3):
        (frames / f"{i}.png").write_bytes(b"not-a-real-png")   # 假引擎不读像素
    out = tmp_path / "r.json"
    rc = bench.main(["--frames", str(frames), "--engines", "rapidocr", "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    e = data["engines"]["rapidocr"]
    assert e["label_hits_total"] >= 6 and e["errors"] == {}
    assert e["latency_s"]["n"] == 3


def test_missing_engine_is_dropped_not_crash(tmp_path, monkeypatch):
    # sys.modules 里没有 rapidocr → main 应剔除该引擎、仍返回 0（记录而非崩溃）
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
    frames = tmp_path / "f"
    frames.mkdir()
    (frames / "0.png").write_bytes(b"x")
    out = tmp_path / "r.json"
    rc = bench.main(["--frames", str(frames), "--engines", "rapidocr", "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["engines"] == {}
