"""T14(1/2)：CLI 退出码合同与离线子命令。"""

from __future__ import annotations

import json

from pddcheck.cli import EXIT_TABLE, ExitCode, exit_for_outcome
from pddcheck.cli.app import main


# --------------------------------------------------------------- 退出码表


def test_exit_table_covers_all_codes():
    for code in ExitCode:
        assert code in EXIT_TABLE


def test_exit_for_outcome_mapping():
    assert exit_for_outcome(rc=0, lit=3) is ExitCode.OK
    assert exit_for_outcome(rc=0, lit=4) is ExitCode.OK        # pend：进程码 0
    assert exit_for_outcome(rc=1, lit=None) is ExitCode.LIGHT_NOT_APPLIED  # 内部未过→6
    assert exit_for_outcome(rc=4, lit=None) is ExitCode.ENTRY_FAILED
    assert exit_for_outcome(rc=5, lit=None) is ExitCode.LOCATE_FAILED
    assert exit_for_outcome(rc=6, lit=None) is ExitCode.LIGHT_NOT_APPLIED
    assert exit_for_outcome(rc=69, lit=None) is ExitCode.NO_ADB
    assert exit_for_outcome(rc=75, lit=None) is ExitCode.LOCK_BUSY


# --------------------------------------------------------------- 子命令


def test_version_runs(capsys):
    assert main(["version"]) == 0
    assert "schema_version" in capsys.readouterr().out


def test_check_config_bad_profile_returns_78(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("[flow]\nnosuch_key = 1\n", encoding="utf-8")
    assert main(["check-config", "--profile", str(bad)]) == int(ExitCode.PRECHECK_FAILED)


def test_doctor_reports_capabilities_without_device(capsys):
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert "device_act" not in out            # 离线能力集不含设备动作
    assert code in (0, int(ExitCode.PRECHECK_FAILED))


def test_replay_incomplete_returns_5(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"run_id": "r"}), encoding="utf-8")
    assert main(["replay", "--run", str(run)]) == int(ExitCode.LOCATE_FAILED)
    assert "缺料" in capsys.readouterr().out


def test_replay_ok_renders_report(tmp_path, capsys):
    run = tmp_path / "run"
    (run / "ocr").mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"run_id": "r", "source_sha256": "x"}), encoding="utf-8")
    (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
        {"seq": 1, "event_name": "check_before", "details": {"before_count": 4}, "wall_time": "t"},
        {"seq": 2, "event_name": "tap", "details": {"tap_method": "ocr"}, "wall_time": "t"},
        {"seq": 3, "event_name": "verify_observation",
         "details": {"stage": "after_direct", "after_count": 3}, "wall_time": "t"},
        {"seq": 4, "event_name": "outcome", "details": {"lit": 3}, "wall_time": "t"},
    ]), encoding="utf-8")
    (run / "ocr" / "f.psm11.tsv").write_text("5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t92\tx\n", encoding="utf-8")
    out_file = tmp_path / "report.html"
    code = main(["replay", "--run", str(run), "--out", str(out_file)])
    assert code == 0
    assert out_file.exists() and "<!DOCTYPE html>" in out_file.read_text(encoding="utf-8")


def test_device_commands_report_not_wired(capsys):
    assert main(["probe"]) == int(ExitCode.NO_ADB)
    assert "尚未接通" in capsys.readouterr().err
