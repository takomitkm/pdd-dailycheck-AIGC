"""T07：Tesseract 适配测试（假 runner，不依赖真二进制）。"""

from __future__ import annotations

import pytest

from pddcheck.domain import ReadStatus
from pddcheck.vision import TesseractConfig, TsvResult, run_tesseract_tsv, tesseract_version


class FakeCompleted:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def test_ok_run_returns_tsv_and_metadata():
    calls = []
    def fake(argv, timeout):
        calls.append((argv, timeout))
        return FakeCompleted(0, "5\t1\t1\t1\t1\t1\t1\t1\t1\t1\t92\t抽福袋\n", "")
    res = run_tesseract_tsv("x.png", 11, TesseractConfig(lang="chi_sim+eng"),
                            engine_version="tesseract 5.5.0", runner=fake)
    assert res.status is ReadStatus.OK and res.error_code is None
    assert "抽福袋" in res.tsv_text
    assert res.engine_version == "tesseract 5.5.0"
    argv, timeout = calls[0]
    assert "--psm" in argv and "tsv" in argv and "chi_sim+eng" in argv
    assert timeout == 8.0


def test_nonzero_rc_is_invalid_with_stderr_tail_not_absent():
    def fake(argv, timeout):
        return FakeCompleted(1, "", "Error in pixReadStream: Unknown image format")
    res = run_tesseract_tsv("x.png", 11, runner=fake)
    assert res.status is ReadStatus.INVALID
    assert res.error_code == "ocr_rc_1"
    assert "pixReadStream" in res.stderr_tail
    assert res.tsv_text == ""


def test_timeout_maps_to_timeout_status():
    def fake(argv, timeout):
        raise TimeoutExpired(argv, timeout)
    from subprocess import TimeoutExpired
    res = run_tesseract_tsv("x.png", 11, runner=fake)
    assert res.status is ReadStatus.TIMEOUT and res.error_code == "ocr_timeout"


def test_missing_binary_is_unavailable():
    from pddcheck.vision.tesseract import TesseractConfig
    res = run_tesseract_tsv("x.png", 11,
                            TesseractConfig(binary="definitely-not-tesseract-xyz"))
    assert res.status is ReadStatus.UNAVAILABLE
    assert res.error_code == "ocr_missing"


def test_version_probe_parses_first_line():
    import subprocess as sp
    real_run = sp.run
    def fake_run(argv, **kw):
        assert argv[-1] == "--version"
        class R: returncode = 0; stdout = "tesseract 5.5.0\nleptonica-1.84.1\n"; stderr = ""
        return R()
    sp.run = fake_run
    try:
        assert tesseract_version() == "tesseract 5.5.0"
    finally:
        sp.run = real_run
