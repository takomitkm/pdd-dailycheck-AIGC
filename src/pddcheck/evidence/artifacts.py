"""内容寻址工件存储（T09）：sha256[:2]/sha256 两级目录，同内容同址，绝不覆盖。"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


class ArtifactCollision(RuntimeError):
    """同路径不同内容——存储被污染或哈希碰撞，绝不静默覆盖。"""


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    sha256: str
    size: int
    codec: str                      # png / tsv / jsonl / txt …

    @property
    def rel_path(self) -> str:
        return f"{self.sha256[:2]}/{self.sha256}.{self.codec}"


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def put(self, data: bytes, codec: str) -> ArtifactRef:
        digest = hashlib.sha256(data).hexdigest()
        rel = ArtifactRef(digest, len(data), codec).rel_path
        target = self.root / rel
        if target.exists():
            existing = target.read_bytes()
            if existing != data:
                raise ArtifactCollision(f"工件路径冲突且内容不同：{rel}")
            return ArtifactRef(digest, len(data), codec)   # 同内容幂等
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + f".tmp-{os.getpid()}")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return ArtifactRef(digest, len(data), codec)

    def open_bytes(self, ref: ArtifactRef) -> bytes:
        return (self.root / ref.rel_path).read_bytes()
