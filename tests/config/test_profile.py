"""T05：profile 模型与严格装载测试。

三条配置闸直接对应桩沙箱用例 44/45/46（acceptance §6）：
44 名单外键停、45 值不成形停、46 标定键不因前缀宽放放行。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pddcheck.config import ConfigError, defaults, load_profile

REPO = Path(__file__).resolve().parents[2]
V1 = REPO / "profiles" / "pdd" / "v1" / "profile.toml"


def test_defaults_spot_checks_against_legacy_values():
    p = defaults()
    assert p.device.pkg == "com.xunmeng.pinduoduo"
    bag = p.target("bag")
    assert bag.coord == (0.13889, 0.69922)      # 旧 COORD_bag (100,895)/720x1280
    assert bag.find_retry == 12                  # FIND_RETRY_bag（轮播位）
    assert p.ocr.psm_band_by_key == (("browse", (7, 6)), ("done", (7, 6)))
    assert p.flow.no_close_lit == (2, 4)         # lit2/lit4 不关 app
    assert p.flow.browse_seconds == 15           # I06：浏览 15 秒墙钟
    assert p.flow.swipe_count == 20              # I06：最终 20 次下滑
    assert p.ocr.count_text == "再点亮|天内点亮"   # 10-16 措辞变更两种都认


def test_v1_toml_never_drifts_from_defaults():
    """profile.toml 是 DEFAULTS 的序列化快照：两者不一致 = 标定漂移，门禁红。"""
    assert load_profile(V1) == defaults()


def test_load_none_returns_defaults():
    assert load_profile(None) is defaults()


def test_unknown_target_rejected(tmp_path):
    bad = V1.read_text(encoding="utf-8") + "\n[targets.nosuch]\nalias = [\"x\"]\n"
    with pytest.raises(ConfigError, match="未知目标"):
        load_profile(_tmp(tmp_path, bad))


def test_unknown_flow_key_rejected(tmp_path):
    bad = V1.read_text(encoding="utf-8").replace(
        "[flow]\n", "[flow]\nstep_wait_fast = 0\n")
    with pytest.raises(ConfigError, match="未知键"):
        load_profile(_tmp(tmp_path, bad))


def test_band_scale_zero_rejected_like_case45(tmp_path):
    bad = V1.read_text(encoding="utf-8").replace("band_scale = 3", "band_scale = 0")
    with pytest.raises(ConfigError, match="band_scale"):
        load_profile(_tmp(tmp_path, bad))


def test_region_out_of_range_rejected(tmp_path):
    bad = V1.read_text(encoding="utf-8").replace(
        "region = [0.0, 0.35, 1.0, 0.85]", "region = [0.0, 0.35, 1.0, 1.85]")
    with pytest.raises(ConfigError, match="0..1"):
        load_profile(_tmp(tmp_path, bad))


def test_pill_mode_invalid_rejected(tmp_path):
    bad = V1.read_text(encoding="utf-8").replace('pill_mode = "color"', 'pill_mode = "gray"')
    with pytest.raises(ConfigError, match="pill_mode"):
        load_profile(_tmp(tmp_path, bad))


def test_cross_reference_unknown_key_rejected(tmp_path):
    bad = V1.read_text(encoding="utf-8").replace(
        'top_retry_key = "subsidy"', 'top_retry_key = "nope"')
    with pytest.raises(ConfigError, match="不存在"):
        load_profile(_tmp(tmp_path, bad))


def _tmp(directory: Path, text: str) -> Path:
    """写进 pytest 的 tmp_path（不污染 CWD，跑完自动清理）。"""
    f = directory / "case.toml"
    f.write_text(text, encoding="utf-8")
    return f
