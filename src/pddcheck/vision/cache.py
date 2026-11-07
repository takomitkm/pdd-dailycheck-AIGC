"""vision 缓存（T16）：解码缓存 + 裁片/预处理缓存，键含内容 hash 与 recipe hash。

键必须含 recipe hash：同一张图在不同 recipe（裁切框/缩放/阈值/模式）下产物不同，
只按图像 hash 命中会把 A recipe 的裁片喂给 B。计数（hit/miss/evict）用于 T16
「调用计数」证据，不靠猜。
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LruCache:
    """通用对象 LRU（存解码句柄或裁片 bytes）。"""

    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._store: OrderedDict[str, object] = OrderedDict()

    def get(self, key: str):
        if key in self._store:
            self._store.move_to_end(key)
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def put(self, key: str, value) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)
            self.evictions += 1

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"hits": self.hits, "misses": self.misses, "evictions": self.evictions,
                "entries": len(self._store),
                "hit_rate": round(self.hits / total, 3) if total else 0.0}


def recipe_key(image_sha: str, box: tuple[int, int, int, int], recipe: str) -> str:
    """裁片缓存键：图像内容 + 裁切框 + recipe 描述（缩放/阈值/模式都进 recipe 串）。"""
    raw = f"{image_sha}|{box[0]},{box[1]},{box[2]},{box[3]}|{recipe}"
    return hashlib.sha256(raw.encode()).hexdigest()


class VisionCache:
    """解码缓存（按图 hash）+ 裁片缓存（按图+框+recipe）。"""

    def __init__(self, max_decoded: int = 8, max_crops: int = 256) -> None:
        self.decoded = LruCache(max_entries=max_decoded)
        self.crops = LruCache(max_entries=max_crops)

    def decode(self, image_bytes: bytes, opener):
        """返回 (解码句柄, image_sha)；同图只解一次。"""
        key = content_hash(image_bytes)
        cached = self.decoded.get(key)
        if cached is not None:
            return cached, key
        handle = opener(image_bytes)
        self.decoded.put(key, handle)
        return handle, key

    def crop(self, image_sha: str, box: tuple[int, int, int, int], recipe: str, maker) -> bytes:
        """返回裁片/预处理产物 bytes；同键只算一次。maker() 产出 bytes。"""
        key = recipe_key(image_sha, box, recipe)
        cached = self.crops.get(key)
        if cached is not None:
            return cached
        out = maker()
        self.crops.put(key, out)
        return out

    def stats(self) -> dict:
        return {"decoded": self.decoded.stats(), "crops": self.crops.stats()}
