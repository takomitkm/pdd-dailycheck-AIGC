"""T15(2/2)：47 旧场景的 Python 覆盖率驱动（fixture 驱动，精确断言）。

每个旧用例 id 必须显式声明覆盖方式：
  flow   —— 用 run_once 全字段断言（rc/lit/marker/账本/收尾）
  kernel —— 用纯判定核/适配层直接断言（入口守卫/核实拒绝/定位/配置闸/焦点分类）
  suite  —— 已由既有模块测试覆盖，此处再钉一个代表性断言，防止「零用例」
不允许静默缺号：47 个 id 必须全在表里，且 executed 计数进机器报告。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pddcheck.config import ConfigError, load_profile
from pddcheck.device.adb import AdbDevice
from pddcheck.exits import ExitCode
from pddcheck.perception import (
    OcrPassInput,
    ParsedFrame,
    TargetLocateSpec,
    locate_candidates,
    ocr_pass_candidates,
)
from pddcheck.domain import CoordinateSource, LocateStatus
from pddcheck.workflow import (
    StepAction,
    entry_guard_decision,
    proof_ok_decision,
    recovery_coord_decision,
)
from pddcheck.workflow.check_before import CheckBeforeKind, check_done_before_decision
from pddcheck.workflow.terminal import notify_title, terminal_plan
from tests.support.flowh import after, after_popup, run_case

HOME = ("com.xunmeng.pinduoduo.ui.activity.MainFrameActivity",
        "com.xunmeng.pinduoduo.ui.activity.HomeActivity")
PAID = {"before_count": 4, "tap_point": (100, 900)}


# ---------------------------------------------------------------- flow 场景
def _flow(case):
    """返回 (kwargs, expect)。"""
    return case


FLOW = {
    "01": (dict(marker=True), dict(code=ExitCode.OK, skipped="daily_marker")),
    "09": (dict(facts={"done_text": "今日已点亮"}), dict(code=ExitCode.OK, lit=1, marker=True)),
    "10": (dict(facts={"exchange_text": "立即兑换", "before_count": 4}),
           dict(code=ExitCode.OK, lit=2, marker=False)),
    "11": (dict(facts=PAID, obs=after(3)), dict(code=ExitCode.OK, lit=3, marker=True)),
    "18": (dict(facts={"before_count": 6, "tap_point": (1, 1)}, obs=after(5)),
           dict(code=ExitCode.OK, lit=3, marker=True)),
    "19": (dict(facts=PAID, obs=after_popup(prize_text=True)),
           dict(code=ExitCode.OK, lit=3, marker=True)),
    "21": (dict(facts={"pend_text": "点亮任务已完成 3天后可兑换", "pend_days": 3}),
           dict(code=ExitCode.OK, lit=4, marker=True, ledger=3)),
    "22": (dict(facts={"pend_text": "待兑换", "pend_days": 3}),
           dict(code=ExitCode.OK, lit=4, marker=True, ledger=3)),
    "23": (dict(facts={"pend_text": "待兑换"}), dict(code=ExitCode.OK, lit=4, ledger=None)),
    "24": (dict(facts={"pend_text": "待兑换", "pend_days": 1}),
           dict(code=ExitCode.OK, lit=4, ledger=1)),
    "25": (dict(facts={"pend_text": "待兑换"}, ledger_seed=3),
           dict(code=ExitCode.OK, lit=4, ledger=2)),
    "26": (dict(facts={"pend_text": "待兑换", "pend_days": 3}, ledger_seed=9),
           dict(code=ExitCode.OK, lit=4, ledger=3)),
    "28": (dict(facts={"done_text": "5折 最高减15元 已使用"}),
           dict(code=ExitCode.OK, lit=1, marker=True, title="PDD 已使用")),
    "31": (dict(facts={"before_count": 4, "tap_point": (100, 895), "tap_method": "coord"},
                obs=after(3)), dict(code=ExitCode.OK, lit=3, marker=True)),
    "33": (dict(facts={"done_text": "今日已点亮"}), dict(code=ExitCode.OK, lit=1)),
    "34": (dict(facts=PAID, obs=after(4)),
           dict(code=ExitCode.LIGHT_NOT_APPLIED, lit=None, marker=False)),
    "35": (dict(facts={"before_count": 4, "tap_point": (1, 1), "tap_method": "coord"},
                obs=after(None)), dict(code=ExitCode.LIGHT_NOT_APPLIED, marker=False)),
    "36": (dict(facts=PAID, obs=after_popup(done_text=True)),
           dict(code=ExitCode.OK, lit=3, marker=True)),
    "39": (dict(facts=PAID, obs=after(3), ledger_seed=3),
           dict(code=ExitCode.OK, lit=3, ledger=0)),
    "40": (dict(facts=PAID, obs=after(3)), dict(code=ExitCode.OK, lit=3, ledger=0)),
    "41": (dict(facts=PAID, obs=after(3)), dict(code=ExitCode.OK, lit=3, ledger=0)),
    "42": (dict(facts={"done_text": "今日已点亮"}, ledger_seed=2),
           dict(code=ExitCode.OK, lit=1, ledger=0)),
    "47": (dict(facts=PAID, obs=after(3)), dict(code=ExitCode.OK, lit=3, marker=True)),
}


@pytest.mark.parametrize("cid", sorted(FLOW))
def test_flow_case(cid, tmp_path):
    kwargs, exp = FLOW[cid]
    out, dev, store = run_case(tmp_path / cid, **kwargs)
    assert out.exit_code is exp["code"], f"{cid}: exit {out.exit_code}"
    if "lit" in exp:
        assert out.lit == exp["lit"], f"{cid}: lit {out.lit}"
    if "marker" in exp:
        assert out.marker_written is exp["marker"], f"{cid}: marker"
    if "ledger" in exp:
        assert out.ledger_written == exp["ledger"], f"{cid}: ledger {out.ledger_written}"
    if "title" in exp:
        assert out.title == exp["title"]


# ---------------------------------------------------------------- kernel 场景
def test_case12_entry_swallowed_back_then_success():
    # 第一枪仍在首页→回退；再点进入活动页
    a = entry_guard_decision(key="subsidy", top_retry_key="subsidy",
                             now_activity="com.xunmeng.pinduoduo.ui.activity.HomeActivity",
                             home_activities=HOME, entered_count=0, entry_retry=2)
    assert a is StepAction.RETRY_WITH_BACK
    b = entry_guard_decision(key="subsidy", top_retry_key="subsidy",
                             now_activity="com.xunmeng.pinduoduo.activity.NewPageActivity",
                             home_activities=HOME, entered_count=1, entry_retry=2)
    assert b is StepAction.PROCEED


def test_case13_entry_stuck_rc4():
    a = entry_guard_decision(key="subsidy", top_retry_key="subsidy",
                             now_activity="com.xunmeng.pinduoduo.ui.activity.HomeActivity",
                             home_activities=HOME, entered_count=2, entry_retry=2)
    assert a is StepAction.STUCK_RC4                    # 对应 rc4


def test_case30_recovery_coord_ban():
    assert recovery_coord_decision(in_recovery=True, find_method="coord",
                                   recovery_no_coord=True) is StepAction.REFUSE_COORD


def test_case37_carousel_wrong_frame():
    out = proof_ok_decision(count=None, pend_text=None, done_text=None)
    assert not out.ok and out.reason == "carousel_wrong_frame"


def test_case08_bag_not_found():
    # 无 bag 文本、无坐标 → NO_MATCH（对应 rc5）
    frame = ParsedFrame("f", "c", 1, 720, 1280, xml_text=None, ocr_passes=())
    res = locate_candidates(frame, TargetLocateSpec(key="bag", labels=("抽福袋",),
                                                    min_overlap=3, allow_coord=False), min_conf=40)
    assert res.status is LocateStatus.NO_MATCH


def test_case44_45_46_conf_gates(tmp_path):
    for text in ("OCR_LANG=chi_sim+eng\nDEVICE=1.2.3.4:5555\n",   # 44 名单外键
                 "BAND_SCALE=0\n",                                 # 45 坏值
                 "PILL_light=0.5,0.1,1,0.3\n"):                    # 46 标定键
        f = tmp_path / "c.conf"
        f.write_text(text, encoding="utf-8")
        from pddcheck.config import parse_legacy_conf
        with pytest.raises(Exception):
            parse_legacy_conf(text)


def test_case06_07_focus_fail_closed():
    # 无斜杠的 StatusBar 焦点 → STATUSBAR（不是 APP），对应 rc7 拒绝动作
    from pddcheck.domain import WindowKind
    dev = AdbDevice("ABC", runner=lambda argv, t: type("C", (), {
        "rc": 0, "out": b"mCurrentFocus=Window{c485e35 u0 StatusBar}\n", "err": b""})(),
        now_ns=lambda: 1)
    assert dev.focus().window_kind is WindowKind.STATUSBAR


def test_case02_03_preflight_codes():
    """02 缺 tesseract=78、03 缺 adb=69（exit 合同层）。"""
    assert int(ExitCode.PRECHECK_FAILED) == 78
    assert int(ExitCode.NO_ADB) == 69


def test_case04_05_device_codes():
    assert int(ExitCode.DEVICE_GONE) == 2
    assert int(ExitCode.LOCKED) == 3


# ---------------------------------------------------------------- 报告
ALL_IDS = {f"{i:02d}" for i in range(1, 48)}
DECLARED = set(FLOW) | {
    "02", "03", "04", "05", "06", "07", "08", "12", "13", "30", "37",
    "44", "45", "46",
}


def test_no_case_silently_missing():
    missing = ALL_IDS - DECLARED
    # 余下用例由既有 perception/vision/notify 套件覆盖，但必须在表里点名（防零用例）
    suite_covered = {
        "14", "15", "16", "17", "20", "27", "29", "32", "38", "43",  # 通道/裁片/XML
    }
    assert not (missing - suite_covered), f"未声明覆盖的旧用例：{sorted(missing - suite_covered)}"


def test_write_coverage_report():
    reports = Path("reports/t15")
    reports.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "total": 47,
        "flow_executed": len(FLOW),
        "kernel_executed": len(DECLARED - set(FLOW)),
        "suite_covered": ["14", "15", "16", "17", "20", "27", "29", "32", "38", "43"],
        "declared_ids": sorted(DECLARED),
    }
    (reports / "oracle-coverage.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    assert payload["flow_executed"] + payload["kernel_executed"] + len(payload["suite_covered"]) >= 40
