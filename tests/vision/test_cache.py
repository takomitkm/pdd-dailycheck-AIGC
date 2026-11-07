"""T16：缓存与预处理测试——LRU 计数、recipe 键隔离、解码/裁片只算一次、
裁切几何与旧 band/pill 一致（用 sandbox compat PIL 真跑）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pddcheck.vision.cache import LruCache, VisionCache, content_hash, recipe_key

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------- LRU


def test_lru_hit_miss_evict():
    c = LruCache(max_entries=2)
    c.put("a", b"1"); c.put("b", b"2")
    assert c.get("a") == b"1"          # hit
    c.get("zzz")                        # miss
    c.put("c", b"3")                    # 触发 evict 最旧的 b
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1 and s["evictions"] == 1


def test_recipe_key_varies_with_recipe_and_box():
    box = (0, 0, 10, 10)
    assert recipe_key("abc", box, "scale=3") != recipe_key("abc", box, "scale=2")
    assert recipe_key("abc", box, "r") != recipe_key("abc", (0, 0, 11, 10), "r")
    assert recipe_key("abc", box, "r") == recipe_key("abc", box, "r")


# --------------------------------------------------------------- 解码/裁片只算一次


def test_decode_once_per_image():
    opened = []
    def opener(b):
        opened.append(b)
        return object()
    vc = VisionCache()
    h1, sha1 = vc.decode(b"PNGDATA", opener)
    h2, sha2 = vc.decode(b"PNGDATA", opener)
    assert opened == [b"PNGDATA"]       # 只解一次
    assert h1 is h2 and sha1 == sha2


def test_crop_once_per_key_and_isolated_by_recipe():
    made = []
    def maker(tag):
        made.append(tag)
        return tag.encode()
    vc = VisionCache()
    a = vc.crop("sha", (0, 0, 4, 4), "scale=3", lambda: maker("s3"))
    b = vc.crop("sha", (0, 0, 4, 4), "scale=3", lambda: maker("s3"))
    c = vc.crop("sha", (0, 0, 4, 4), "scale=2", lambda: maker("s2"))
    assert a == b == b"s3" and c == b"s2"
    assert made == ["s3", "s2"]         # 同键只算一次；不同 recipe 各算一次


# --------------------------------------------------------------- 裁切几何（纯）


def test_band_crop_box_matches_legacy_padding():
    from pddcheck.vision.preprocess import band_crop_box
    # region 0.35..0.85 高，图 720x1280；pad_y=0.015
    x0, y0, w, h = band_crop_box((0.0, 0.35, 1.0, 0.85), 720, 1280)
    assert x0 == 0 and y0 == int((0.35 - 0.015) * 1280)
    assert (x0 + w, y0 + h) == (720, int((0.85 + 0.015) * 1280))


def test_pill_crop_box_no_padding():
    from pddcheck.vision.preprocess import pill_crop_box
    x0, y0, w, h = pill_crop_box((0.5, 0.1, 0.9, 0.2), 1000, 2000)
    assert (x0, y0, w, h) == (500, 200, 400, 200)


# --------------------------------------------------------------- 预处理（compat PIL 真跑）


def test_preprocess_band_and_pill_with_compat_pil():
    sys.path.insert(0, str(ROOT / "sandbox" / "pylib"))
    try:
        from PIL import Image
        from pddcheck.vision.preprocess import preprocess_band, preprocess_pill
    except Exception as exc:            # compat 层不可用则跳过（不误红）
        pytest.skip(f"compat PIL 不可用：{exc}")
    img = Image.new("RGB", (40, 20), (200, 180, 160))
    band = preprocess_band(img, (0, 0, 40, 20), scale=3, cutoff=1)
    assert band.width == 120 and band.height == 60
    pill = preprocess_pill(img, (0, 0, 40, 20), div=2, th=120, mode="inv")
    assert pill.width == 80 and pill.height == 40
    # color 模式不转灰度、不放大
    pill_c = preprocess_pill(img, (0, 0, 40, 20), div=1, th=120, mode="color")
    assert pill_c.width == 40 and pill_c.height == 20
