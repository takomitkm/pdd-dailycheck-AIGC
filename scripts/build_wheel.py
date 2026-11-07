"""构建纯 Python wheel（仅标准库，离线、确定）。

产出的 wheel 是标准 zip：pddcheck/** + pddcheck-<ver>.dist-info/{METADATA,WHEEL,RECORD}。
RECORD 用 urlsafe-base64(sha256) 无 padding 的记录格式（PEP 427）。
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
NAME = "pddcheck"


def _version() -> str:
    ns: dict = {}
    exec((SRC / "pddcheck" / "__init__.py").read_text(encoding="utf-8"), ns) if False else None
    for line in (SRC / "pddcheck" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def _hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _files() -> list[tuple[str, bytes]]:
    out = []
    for p in sorted((SRC / NAME).rglob("*.py")):
        rel = p.relative_to(SRC).as_posix()
        out.append((rel, p.read_bytes()))
    return out


def build(dist_dir: Path | None = None, version: str | None = None) -> Path:
    version = version or _version()
    dist_dir = Path(dist_dir or ROOT / "dist")
    dist_dir.mkdir(parents=True, exist_ok=True)
    wheel_name = f"{NAME}-{version}-py3-none-any.whl"
    wheel_path = dist_dir / wheel_name
    dist_info = f"{NAME}-{version}.dist-info"

    files = _files()
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {NAME}\n"
        f"Version: {version}\n"
        "Summary: PDD 每日签到自动化（refactor-v2）\n"
        "Requires-Python: >=3.11\n"
        "\n"
    ).encode()
    wheel_meta = (
        "Wheel-Version: 1.0\n"
        "Generator: pddcheck.stdbuild\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
        "\n"
    ).encode()
    entry = f"[console_scripts]\npddcheck = pddcheck.cli.app:_console\n"

    records: list[tuple[str, str, str]] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, data in files:
            zf.writestr(rel, data)
            records.append((rel, _hash(data), str(len(data))))
        zf.writestr(f"{dist_info}/METADATA", metadata)
        records.append((f"{dist_info}/METADATA", _hash(metadata), str(len(metadata))))
        zf.writestr(f"{dist_info}/WHEEL", wheel_meta)
        records.append((f"{dist_info}/WHEEL", _hash(wheel_meta), str(len(wheel_meta))))
        zf.writestr(f"{dist_info}/entry_points.txt", entry)
        eb = entry.encode()
        records.append((f"{dist_info}/entry_points.txt", _hash(eb), str(len(eb))))
        # RECORD 自身哈希为空
        rec = io.StringIO()
        w = csv.writer(rec, lineterminator="\n")
        for row in records:
            w.writerow(row)
        w.writerow((f"{dist_info}/RECORD", "", ""))
        zf.writestr(f"{dist_info}/RECORD", rec.getvalue())
    wheel_path.write_bytes(buf.getvalue())
    return wheel_path


if __name__ == "__main__":
    p = build(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(p)
