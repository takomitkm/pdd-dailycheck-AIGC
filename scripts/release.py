"""发布管理（T17）：不可变 release 目录 + 原子指针 + pause/resume + 回滚。

布局：
  <root>/releases/<version>/pddcheck-<ver>-py3-none-any.whl
  <root>/releases/<version>/manifest.json      # 每个文件的 SHA256，只读
  <root>/current                               # 文本：当前版本号（原子替换）
  <root>/paused                                # 存在=暂停（timer 不再触发业务）

规则：
- release 目录只写一次（build 时）；已存在且 manifest 不符 → 拒绝重建；
- switch 前校验 manifest；损坏/不符 → 拒绝切换（不伪称成功）；
- rollback = 切回 previous（记录在 current 切换前的值，写入 <root>/previous）；
- 绝不操作真实 systemd；pause/resume 只动 paused 文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import build_wheel


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@dataclass(frozen=True)
class Release:
    root: Path
    version: str

    @property
    def dir(self) -> Path:
        return self.root / "releases" / self.version

    @property
    def manifest(self) -> Path:
        return self.dir / "manifest.json"


class ReleaseError(RuntimeError):
    pass


def build_release(root: Path, version: str | None = None) -> Release:
    tmp_dist = root / ".build"
    tmp_dist.mkdir(parents=True, exist_ok=True)
    wheel = build_wheel.build(tmp_dist, version)
    version = wheel.name.split("-")[1]
    rel = Release(root, version)
    if rel.dir.exists():
        # 已存在：校验一致则幂等，否则拒绝（不可变）
        if _verify(rel) and (rel.dir / wheel.name).read_bytes() == wheel.read_bytes():
            return rel
        raise ReleaseError(f"release {version} 已存在且内容不符，拒绝重建（不可变）")
    rel.dir.mkdir(parents=True)
    target = rel.dir / wheel.name
    target.write_bytes(wheel.read_bytes())
    manifest = {
        "schema_version": 1,
        "version": version,
        "files": {wheel.name: _sha256(target)},
    }
    (rel.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return rel


def _verify(rel: Release) -> bool:
    try:
        data = json.loads(rel.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for name, digest in data.get("files", {}).items():
        f = rel.dir / name
        if not f.exists() or _sha256(f) != digest:
            return False
    return bool(data.get("files"))


def current_version(root: Path) -> str | None:
    p = root / "current"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def switch(root: Path, version: str) -> Release:
    rel = Release(root, version)
    if not rel.dir.exists():
        raise ReleaseError(f"release {version} 不存在")
    if not _verify(rel):
        raise ReleaseError(f"release {version} manifest 校验失败，拒绝切换")
    prev = current_version(root)
    if prev and prev != version:
        _atomic_text(root / "previous", prev + "\n")
    _atomic_text(root / "current", version + "\n")   # 原子指针切换
    return rel


def rollback(root: Path) -> str:
    prev_file = root / "previous"
    if not prev_file.exists():
        raise ReleaseError("没有可回滚的 previous")
    prev = prev_file.read_text(encoding="utf-8").strip()
    switch(root, prev)                                # 会先把当前写入 previous
    return prev


def pause(root: Path) -> None:
    _atomic_text(root / "paused", "1\n")


def resume(root: Path) -> None:
    (root / "paused").unlink(missing_ok=True)


def is_paused(root: Path) -> bool:
    return (root / "paused").exists()


def status(root: Path) -> dict:
    return {"current": current_version(root), "paused": is_paused(root),
            "releases": sorted(p.name for p in (root / "releases").glob("*") if p.is_dir())
            if (root / "releases").exists() else []}


def expand(root: Path, version: str) -> Path:
    """把 release 的 wheel 解包到 releases/<ver>/site（staging/安装用，stdlib 离线）。"""
    rel = Release(root, version)
    if not rel.dir.exists() or not _verify(rel):
        raise ReleaseError(f"release {version} 不存在或 manifest 不符，拒绝展开")
    wheel = next(rel.dir.glob("*.whl"))
    site = rel.dir / "site"
    site.mkdir(exist_ok=True)
    import zipfile
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if ".dist-info/" in name:
                continue
            zf.extract(name, site)
    return site


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="release")
    ap.add_argument("--root", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--version", default=None)
    e = sub.add_parser("expand"); e.add_argument("version")
    s = sub.add_parser("switch"); s.add_argument("version")
    sub.add_parser("rollback"); sub.add_parser("pause"); sub.add_parser("resume")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    root = Path(a.root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        if a.cmd == "build":
            print(build_release(root, a.version).version)
        elif a.cmd == "expand":
            print(expand(root, a.version))
        elif a.cmd == "switch":
            switch(root, a.version); print("ok")
        elif a.cmd == "rollback":
            print(rollback(root))
        elif a.cmd == "pause":
            pause(root); print("paused")
        elif a.cmd == "resume":
            resume(root); print("resumed")
        elif a.cmd == "status":
            print(json.dumps(status(root), ensure_ascii=False))
    except ReleaseError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
