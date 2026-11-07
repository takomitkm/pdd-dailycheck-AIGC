"""ADR-003：profile 的 pill_channel 字段——批准前缺省关闭，批准后写入即生效。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pddcheck.config.errors import ConfigError
from pddcheck.config.profile import DEFAULTS, load_profile

V1 = Path(__file__).resolve().parents[2] / "profiles" / "pdd" / "v1" / "profile.toml"


def test_pill_channel_absent_means_none():
    """现有 v1 profile 未批准 → bag.pill_channel 关闭（防漂移口径的一部分）。"""
    spec = DEFAULTS.target("bag")
    assert spec.pill_channel is None
    p = load_profile(V1)
    assert p.target("bag").pill_channel is None
    assert p.target("bag").pill == (0.02, 0.64, 0.32, 0.78)   # 原框不受影响


def test_pill_channel_written_loads(tmp_path):
    text = V1.read_text(encoding="utf-8")
    assert "[targets.bag]" in text
    patched = text.replace("[targets.bag]",
                           "[targets.bag]\npill_channel = [0.472, 0.375, 0.75, 0.4375]", 1)
    f = tmp_path / "profile.toml"
    f.write_text(patched, encoding="utf-8")
    p = load_profile(f)
    assert p.target("bag").pill_channel == (0.472, 0.375, 0.75, 0.4375)
    assert p.target("bag").pill == (0.02, 0.64, 0.32, 0.78)


def test_pill_channel_out_of_range_rejected(tmp_path):
    text = V1.read_text(encoding="utf-8")
    patched = text.replace("[targets.bag]",
                           "[targets.bag]\npill_channel = [1.5, 0.375, 0.75, 0.4375]", 1)
    f = tmp_path / "profile.toml"
    f.write_text(patched, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_profile(f)
