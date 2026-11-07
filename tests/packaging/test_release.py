"""T17：打包与发布测试——wheel 合法性、manifest 校验、原子切换、回滚、拒切损坏、
pause/resume、展开后可运行、launcher 语法。全部离线、临时目录内，不触 systemd。"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_wheel  # noqa: E402
import release  # noqa: E402


# --------------------------------------------------------------- wheel


def test_wheel_is_valid_and_record_matches(tmp_path):
    whl = build_wheel.build(tmp_path)
    assert whl.name.startswith("pddcheck-") and whl.suffix == ".whl"
    with zipfile.ZipFile(whl) as zf:
        names = zf.namelist()
        assert "pddcheck/__init__.py" in names
        dist_info = next(n for n in names if n.endswith(".dist-info/RECORD"))
        record = zf.read(dist_info).decode()
        for line in record.strip().splitlines():
            path, digest, size = line.split(",")
            if digest:
                import base64
                import hashlib
                want = "sha256=" + base64.urlsafe_b64encode(
                    hashlib.sha256(zf.read(path)).digest()).decode().rstrip("=")
                assert digest == want, f"{path} RECORD 哈希不符"


# --------------------------------------------------------------- release 生命周期


def _build(root, version="0.1.0"):
    return release.build_release(root, version)


def test_build_release_writes_manifest_and_is_immutable(tmp_path):
    rel = _build(tmp_path)
    assert rel.manifest.exists()
    data = json.loads(rel.manifest.read_text(encoding="utf-8"))
    wheel = next(rel.dir.glob("*.whl"))
    import hashlib
    assert data["files"][wheel.name] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    # 同版本重建（内容一致）幂等；篡改后重建被拒（不可变）
    assert _build(tmp_path).version == rel.version
    wheel.write_bytes(b"tampered")
    with pytest.raises(release.ReleaseError, match="不可变"):
        _build(tmp_path)


def test_switch_and_rollback(tmp_path):
    _build(tmp_path, "0.1.0")
    _build(tmp_path, "0.2.0")
    release.switch(tmp_path, "0.1.0")
    assert release.current_version(tmp_path) == "0.1.0"
    release.switch(tmp_path, "0.2.0")
    assert release.current_version(tmp_path) == "0.2.0"
    assert release.rollback(tmp_path) == "0.1.0"
    assert release.current_version(tmp_path) == "0.1.0"


def test_switch_refuses_corrupt_release(tmp_path):
    _build(tmp_path, "0.1.0")
    _build(tmp_path, "0.2.0")
    release.switch(tmp_path, "0.2.0")
    wheel = next((tmp_path / "releases" / "0.1.0").glob("*.whl"))
    wheel.write_bytes(b"corrupt")
    with pytest.raises(release.ReleaseError, match="manifest"):
        release.switch(tmp_path, "0.1.0")
    assert release.current_version(tmp_path) == "0.2.0"   # 指针未动


def test_switch_missing_release_refused(tmp_path):
    with pytest.raises(release.ReleaseError, match="不存在"):
        release.switch(tmp_path, "9.9.9")


def test_pause_resume(tmp_path):
    _build(tmp_path)
    assert not release.is_paused(tmp_path)
    release.pause(tmp_path)
    assert release.is_paused(tmp_path)
    release.resume(tmp_path)
    assert not release.is_paused(tmp_path)


def test_expand_then_run_module(tmp_path):
    rel = _build(tmp_path)
    site = release.expand(tmp_path, rel.version)
    assert (site / "pddcheck" / "__init__.py").exists()
    # PYTHONPATH=site 能真正跑起 CLI（version 子命令）
    proc = subprocess.run([sys.executable, "-m", "pddcheck.cli.app", "version"],
                          env={"PYTHONPATH": str(site), "PATH": ""},
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "schema_version" in proc.stdout


def test_launcher_script_syntax():
    """sh -n 语法检查；Windows 无 POSIX sh 时跳过（Debian 上真跑）。"""
    import os
    if os.name == "nt":
        pytest.skip("Windows 无 POSIX sh；launcher 在 Debian 上验证")
    script = ROOT / "packaging" / "launcher.sh"
    proc = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_systemd_candidate_has_no_restart():
    text = (ROOT / "packaging" / "systemd" / "pddcheck.service.candidate").read_text(encoding="utf-8")
    assert "Restart=no" in text
    assert "Type=oneshot" in text
    directives = [ln.strip() for ln in text.splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
    assert not any(d.startswith("ExecStartPre") for d in directives)   # 连接不放在 ExecStartPre（D03）
