"""T05：旧 pdd-ocr.conf 兼容解析器测试（逐条对齐 load_ocr_conf + ocr_conf_check）。"""

from __future__ import annotations

import pytest

from pddcheck.config import LegacyConfError, load_optional_legacy_conf, parse_legacy_conf

VALID = """\
# 注释行要跳过
OCR_LANG=chi_sim+eng
OCR_PSM=11
OCR_PSM_PAGE=6
OCR_MINCONF=40
OCR_PSM_BAND=7
OCR_PSM_BAND_browse=7 6
OCR_PSM_BAND_done=7 6
PEND_PSM=6 11 12
BAND_SCALE=3
BAND_CUTOFF=1
PILL_TH=120
PILL_SCALES=1 2
PILL_MODE_bag=color

VLM_BACKEND=local
PDD_SH=/tmp/pdd.sh
"""


def test_valid_conf_applies_and_counts_foreign():
    conf = parse_legacy_conf(VALID)
    assert conf.applied == 13
    assert conf.foreign == 2                      # VLM_BACKEND + PDD_SH：认得不应用
    assert conf.get("OCR_LANG") == "chi_sim+eng"
    assert conf.get("OCR_PSM_BAND_browse") == "7 6"
    assert conf.band_by_key() == (("browse", "7 6"), ("done", "7 6"))
    assert conf.modes_by_key() == (("bag", "color"),)


def test_unknown_key_stops_like_case44():
    # DEVICE 在旧名单外（它是设备/标定，不是 OCR 调用）——写进来必须当场停
    with pytest.raises(LegacyConfError, match="不在名单里"):
        parse_legacy_conf("OCR_LANG=chi_sim+eng\nDEVICE=192.168.1.9:5555\n")


def test_calibration_box_stops_like_case46():
    # PILL_light 是标定框：按前缀宽放它就等于给标定数据开后门（旧 78 语义）
    with pytest.raises(LegacyConfError, match="不在名单里"):
        parse_legacy_conf("PILL_light=0.5,0.1,1,0.3\n")


def test_band_scale_zero_stops_like_case45():
    with pytest.raises(LegacyConfError, match="1..8"):
        parse_legacy_conf("BAND_SCALE=0\n")


def test_psm_out_of_range_stops():
    with pytest.raises(LegacyConfError, match="0..32"):
        parse_legacy_conf("OCR_PSM=33\n")


def test_bad_int_list_stops():
    with pytest.raises(LegacyConfError, match="整数表"):
        parse_legacy_conf("OCR_PSM_BAND_browse=7 x\n")


def test_mode_value_stops():
    with pytest.raises(LegacyConfError, match="inv|color"):
        parse_legacy_conf("PILL_MODE_bag=gray\n")


def test_credential_key_stops_hard():
    with pytest.raises(LegacyConfError, match="凭据"):
        parse_legacy_conf("VLM_API_KEY=sk-xxxx\n")


def test_empty_key_and_non_kv_stop_with_line_number():
    with pytest.raises(LegacyConfError, match="第 1 行"):
        parse_legacy_conf("=x\n")
    with pytest.raises(LegacyConfError, match="第 1 行"):
        parse_legacy_conf("就是一行字\n")


def test_blank_lines_and_crlf_tolerated():
    conf = parse_legacy_conf("\r\nOCR_LANG=chi_sim+eng\r\n\r\n# c\r\n")
    assert conf.get("OCR_LANG") == "chi_sim+eng"


def test_optional_loader_missing_or_unreadable_returns_none(tmp_path):
    assert load_optional_legacy_conf(tmp_path / "absent.conf") is None
    # Windows 上 chmod 000 不挡读；用一个目录路径触发 OSError（exists=True 但 read 失败）
    assert load_optional_legacy_conf(tmp_path / "as-dir") is None   # B01：回退由调用方记 warning
    broken = tmp_path / "broken.conf"
    broken.write_text("DEVICE=x\n", encoding="utf-8")
    with pytest.raises(LegacyConfError):                       # 内容坏 = D06，必须失败
        load_optional_legacy_conf(broken)
