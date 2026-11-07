"""原子写：同目录 temp → flush/fsync → os.replace → 目录 fsync（契约 §10）。

失败语义：任何一步抛 OSError，目标文件保持旧内容（replace 是原子的）；
调用方据此区分「业务成功但状态未落盘」（operational_status，D04）。
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write(path: Path, data: bytes) -> None:
    path = Path(path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{path.name}.tmp-{os.getpid()}"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        # replace 成功后 tmp 已不存在；失败路径上清掉半截 temp
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    _fsync_dir(directory)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write(path, text.encode("utf-8"))


def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
