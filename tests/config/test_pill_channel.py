"""ADR-003：profile 的 pill_channel 字段——批准前缺省关闭，批准后写入即生效。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pddcheck.config.errors import ConfigError
from pddcheck.config.profile import DEFAULTS, load_profile

V1 = Path(__file__).resolve().parents[2] / "profiles" / "pdd" / "v1" / "profile.toml"


def test_pill_channel_defaults_absent_v1_approved():
    """DEFAULTS 里 code-default 的 pill_channel 语义与 v1 批准值分离；
    批准后 v1 profile 与 DEFAULTS 一致（防漂移由 test_profile 保证）。"""
    p = load_profile(V1)
    assert p.target("bag").pill_channel == (0.472, 0.375, 0.75, 0.4375)
    assert p.target("bag").pill == (0.02, 0.64, 0.32, 0.78)   # 原框不受影响


def test_pill_channel_written_loads(tmp_path):
    text = V1.read_text(encoding="utf-8")
    # v1 已含批准值；替换成另一个合法值，证明加载器确实读该字段
    assert "pill_channel = [0.472, 0.375, 0.75, 0.4375]" in text
    patched = text.replace("pill_channel = [0.472, 0.375, 0.75, 0.4375]",
                           "pill_channel = [0.5, 0.4, 0.8, 0.45]", 1)
    f = tmp_path / "profile.toml"
    f.write_text(patched, encoding="utf-8")
    p = load_profile(f)
    assert p.target("bag").pill_channel == (0.5, 0.4, 0.8, 0.45)
    assert p.target("bag").pill == (0.02, 0.64, 0.32, 0.78)


def test_pill_channel_out_of_range_rejected(tmp_path):
    text = V1.read_text(encoding="utf-8")
    patched = text.replace("pill_channel = [0.472, 0.375, 0.75, 0.4375]",
                           "pill_channel = [1.5, 0.375, 0.75, 0.4375]", 1)
    f = tmp_path / "profile.toml"
    f.write_text(patched, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_profile(f)
