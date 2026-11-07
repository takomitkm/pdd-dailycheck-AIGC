"""T15/T16：真语料健壮性——356 份 TSV + 150 份 XML 全部不崩、可复现。

语料在仓库外（pdd-corpus-private）；不存在则跳过（CI 无私有语料时不误红）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pddcheck.perception import (
    OcrPassInput,
    ocr_pass_candidates,
    parse_tsv,
    xml_pass_candidates,
)
from pddcheck.domain import CoordinateSource

CORPUS = Path(os.environ.get("PDD_CORPUS", "S:/apps/llm/agentwork/pdd-corpus-private"))
RUNS = CORPUS / "pdd-runs"
OCR = CORPUS / "ocr-v1"

pytestmark = pytest.mark.skipif(not RUNS.exists(), reason="无私有语料（跳过）")


def test_all_corpus_xml_parse_and_deterministic():
    xmls = sorted(RUNS.rglob("*.xml"))
    assert xmls, "语料应含 XML"
    for p in xmls:
        text = p.read_text(encoding="utf-8", errors="replace")
        c1 = xml_pass_candidates("f", "c", 1, text, "k", ("抽福袋",), min_overlap=2)
        c2 = xml_pass_candidates("f", "c", 1, text, "k", ("抽福袋",), min_overlap=2)
        assert [x.tap_point for x in c1] == [x.tap_point for x in c2], p.name


def test_all_corpus_tsv_parse_and_deterministic():
    tsvs = sorted(OCR.glob("*.tsv")) if OCR.exists() else []
    if not tsvs:
        pytest.skip("无 OCR 工件（跳过）")
    labels = ("抽福袋", "立即点亮", "今日已点亮", "已使用", "百亿补贴")
    for p in tsvs:
        text = p.read_text(encoding="utf-8", errors="replace")
        lines1 = parse_tsv(text)
        lines2 = parse_tsv(text)
        assert len(lines1) == len(lines2), p.name
        a = ocr_pass_candidates("f", "c", 1,
                                OcrPassInput(source=CoordinateSource.TESSERACT_PAGE, tsv_text=text),
                                "k", labels, min_overlap=2, min_conf=40)
        b = ocr_pass_candidates("f", "c", 1,
                                OcrPassInput(source=CoordinateSource.TESSERACT_PAGE, tsv_text=text),
                                "k", labels, min_overlap=2, min_conf=40)
        assert [(x.tap_point, x.overlap) for x in a] == [(x.tap_point, x.overlap) for x in b], p.name


def test_corpus_has_no_crash_on_garbage_tsv():
    # 垃圾输入也必须不崩（返回空/部分），这是「空结果≠错误」的边界
    for junk in ("", "\x00\x01", "1\t2\n", "5\t1\t1\t1\t1\t1\tx\ty\tz", "5\t1\t1\t1\t1\t1\t1\t1\t1\t1\tabc\t字"):
        parse_tsv(junk)  # 不抛
