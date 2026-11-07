"""T38：PDDCHECK_DEVICE 环境变量——timer 场景的设备序列来源（禁止自动选设备不变）。"""

from __future__ import annotations

import pytest

from pddcheck.cli.app import _build_parser, _cmd_run


def test_run_without_device_or_env_fails_no_adb(monkeypatch, tmp_path):
    monkeypatch.delenv("PDDCHECK_DEVICE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    args = _build_parser().parse_args(["run"])
    res = _cmd_run(args)
    assert res.code == 69 and "PDDCHECK_DEVICE" in res.stderr


def test_run_with_env_device_accepted(monkeypatch, tmp_path):
    """环境变量被接受：报的是**连接失败**（adb_failed），不是「没给设备」。"""
    monkeypatch.setenv("PDDCHECK_DEVICE", "1.2.3.4:5555")
    monkeypatch.setenv("HOME", str(tmp_path))
    args = _build_parser().parse_args(["run"])
    res = _cmd_run(args)
    assert "adb_failed" in res.stderr and "PDDCHECK_DEVICE" not in res.stderr
