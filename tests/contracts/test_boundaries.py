"""依赖边界测试（契约 §1）：业务层禁止 import 设备/视觉第三方库。

用 AST 扫描而不是 import 试错：即使包没安装也能发现越界；白名单只放行
标准库与 pddcheck 自身。device/、vision/ 两个适配器目录是未来唯一允许
出现 adbutils/uiautomator2/RapidOCR/Pillow 的地方，当前尚不存在，出现即红。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "pddcheck"

FORBIDDEN_THIRD_PARTY = {
    "adbutils",
    "uiautomator2",
    "rapidocr_onnxruntime",
    "rapidocr",
    "PIL",
    "cv2",
    "numpy",
    "requests",
    "httpx",
    "flask",
    "fastapi",
}

# 业务层（无任何设备/视觉依赖）；适配器目录将来单独放行白名单。
BUSINESS_PACKAGES = ("domain", "perception", "workflow", "storage", "evidence", "notify", "replay", "config")


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _python_files() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for pkg in BUSINESS_PACKAGES:
        pkg_dir = SRC / pkg
        if not pkg_dir.is_dir():
            continue
        for py in sorted(pkg_dir.rglob("*.py")):
            out.append((f"pddcheck/{pkg}/{py.relative_to(pkg_dir)}", py))
    root_init = SRC / "__init__.py"
    if root_init.is_file():
        out.append(("pddcheck/__init__.py", root_init))
    return out


@pytest.mark.parametrize("rel,path", _python_files(), ids=lambda x: x)
def test_business_modules_are_stdlib_only(rel: str, path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = _imported_roots(tree)
    bad = roots & FORBIDDEN_THIRD_PARTY
    assert not bad, f"{rel} 越界 import：{sorted(bad)}（契约 §1：业务层只依赖标准库）"


def test_domain_never_imports_sibling_adapters():
    """domain 连自家适配器都不准碰（它是被所有层依赖的最底层）。"""
    for py in sorted((SRC / "domain").rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        roots = _imported_roots(tree)
        bad = roots & {"device", "vision", "perception", "workflow", "storage", "evidence", "notify", "replay"}
        assert not bad, f"domain/{py.name} import 了兄弟包 {sorted(bad)}"
