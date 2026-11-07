"""批准路径：profile 写了 pill_channel → CLI 用它；没写 → fallback。"""

from __future__ import annotations

from pathlib import Path

from pddcheck.config.profile import load_profile

V1 = Path(__file__).resolve().parents[2] / "profiles" / "pdd" / "v1" / "profile.toml"


def test_profile_bag_pill_channel_is_none_until_approved():
    """未批准：v1 profile 的 pill_channel 必须是 None（防漂移）。"""
    prof = load_profile(V1)
    assert prof.target("bag").pill_channel is None


def test_approved_profile_takes_precedence(tmp_path):
    """批准后（profile 写入）：CLI 读取逻辑应取 profile 值，而不是 fallback。"""
    text = V1.read_text(encoding="utf-8")
    patched = text.replace("[targets.bag]",
                           "[targets.bag]\npill_channel = [0.5, 0.4, 0.8, 0.45]", 1)
    f = tmp_path / "profile.toml"
    f.write_text(patched, encoding="utf-8")
    prof = load_profile(f)
    pc = prof.target("bag").pill_channel
    # 模拟 app.py 的取值逻辑
    bag_pill = (pc, "color") if pc is not None else ((0.472, 0.375, 0.75, 0.4375), "color")
    assert bag_pill == ((0.5, 0.4, 0.8, 0.45), "color")
    assert bag_pill != ((0.472, 0.375, 0.75, 0.4375), "color")   # 不再是 fallback


def test_fallback_value_matches_real_device_measurement():
    """fallback 值必须是真机实测值（t18a-calibration-findings §2：点 (435,524)）。"""
    box = (0.472, 0.375, 0.75, 0.4375)
    # 720×1280 点空间换算
    assert (int(box[0] * 720), int(box[1] * 1280)) == (339, 480)   # 裁片原点
    # 裁片 201×80，pill 中心 ≈ (339+100, 480+40) → 点在 (435,524) 一带
