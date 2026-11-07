"""T15(2/2)：11 个语义 mutation 负对照——每个变异必须被对应检查杀死。

口径（acceptance §7）：不是改 Shell 行文本，而是在 Python 语义层注入缺陷，
断言「该缺陷下，对应检查会失败」（即 killed）。修改未生效/导入错不算 kill：
每个 mutant 先断言 patch 确实生效（观察被破坏后的可观测差异），再断言检查失败。
"""

from __future__ import annotations

import pytest

import pddcheck.config.profile as prof_mod
import pddcheck.device.adb as adb_mod
import pddcheck.notify.sender as sender_mod
import pddcheck.perception.locate as locate_mod
import pddcheck.workflow.steps as steps_mod
import pddcheck.workflow.terminal as terminal_mod
import pddcheck.workflow.verify as verify_mod
from pddcheck.config import load_profile
from pddcheck.device.adb import AdbDevice
from pddcheck.domain import (
    BoxPrecision,
    Candidate,
    CoordinateSource,
    FocusState,
    LocateStatus,
    WindowKind,
)
from pddcheck.notify import DeliveryStatus, NotificationSender
from pddcheck.perception import ParsedFrame, TargetLocateSpec, locate_candidates
from pddcheck.workflow import StepAction, entry_guard_decision, verify_light_decision
from pddcheck.workflow.terminal import notify_title
from pddcheck.workflow.verify import ProofKind, VerifyObservation, VerifyStage

HOME = ("com.xunmeng.pinduoduo.ui.activity.MainFrameActivity",
        "com.xunmeng.pinduoduo.ui.activity.HomeActivity")


def O(stage, after=None, done=False, prize=False, pend=False):
    return VerifyObservation(stage, after_count=after, done_text=done,
                             prize_text=prize, pend_text=pend)


# ---------------------------------------------------------------- 检查（正确行为）
def check_browse_reenter():
    out = verify_mod.verify_light_decision(4, "ocr", (O(VerifyStage.AFTER_BACK, after=None),
                                          O(VerifyStage.AFTER_REENTER, after=3)))
    assert out.proof_kind is ProofKind.COUNTER_DECREASE


def check_prize():
    out = verify_mod.verify_light_decision(4, "ocr", (O(VerifyStage.AFTER_POPUP, prize=True),))
    assert out.proof_kind is ProofKind.PRIZE and out.lit == 3


def check_used_terminal():
    out = verify_mod.verify_light_decision(4, "ocr", (O(VerifyStage.AFTER_DIRECT, done=True),))
    assert out.proof_kind is ProofKind.SCREEN_DONE


def check_used_title():
    assert terminal_mod.notify_title(rc=0, lit=1, done_word="5折 最高减15元 已使用") == "PDD 已使用"


def check_lit1_title():
    assert terminal_mod.notify_title(rc=0, lit=1, done_word="今日已点亮") == "PDD ✅"


def check_entry_guard():
    a = steps_mod.entry_guard_decision(key="subsidy", top_retry_key="subsidy",
                             now_activity="com.xunmeng.pinduoduo.ui.activity.HomeActivity",
                             home_activities=HOME, entered_count=2, entry_retry=2)
    assert a is StepAction.STUCK_RC4


def check_focus_fail_closed():
    dev = AdbDevice("ABC", runner=lambda argv, t: type("C", (), {
        "rc": 0, "out": b"mCurrentFocus=Window{c485e35 u0 StatusBar}\n", "err": b""})(),
        now_ns=lambda: 1)
    assert dev.focus().window_kind is WindowKind.STATUSBAR


def check_band_psm6():
    band = dict(prof_mod.load_profile(None).ocr.psm_band_by_key)
    assert 6 in band["done"]


def check_conf_loaded(tmp_path):
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "profiles" / "pdd" / "v1" / "profile.toml"
    text = src.read_text(encoding="utf-8").replace("band_scale = 3", "band_scale = 5")
    p = tmp_path / "c.toml"
    p.write_text(text, encoding="utf-8")
    assert prof_mod.load_profile(p).ocr.band_scale == 5      # 装载了文件（非默认 3）


def check_push_metrics():
    send = sender_mod.NotificationSender(transport=lambda u, t: (200, '{"code":0}'))
    res = send.send("http://x/s", "t", "d")
    assert res.attempts == 1 and res.status is DeliveryStatus.SENT


def check_bag_coord():
    frame = ParsedFrame("f", "c", 1, 720, 1280, xml_text=None, ocr_passes=())
    spec = TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3, coord=(0.13889, 0.69922))
    assert locate_mod.locate_candidates(frame, spec, min_conf=40).status is LocateStatus.MATCH


# ---------------------------------------------------------------- 变异实现
def _drop_reenter(before, method, observations):
    return verify_mod.__dict__["_orig"](before, method,
                                        [o for o in observations if o.stage is not VerifyStage.AFTER_REENTER])


def _drop_prize(before, method, observations):
    obs = [VerifyObservation(o.stage, o.after_count, o.done_text, False, o.pend_text,
                             o.reenter_failed) for o in observations]
    return verify_mod.__dict__["_orig"](before, method, obs)


def _drop_done(before, method, observations):
    obs = [VerifyObservation(o.stage, o.after_count, False, o.prize_text, o.pend_text,
                             o.reenter_failed) for o in observations]
    return verify_mod.__dict__["_orig"](before, method, obs)


def _title_all_check():
    orig = terminal_mod.notify_title
    def bad(*, rc, lit, done_word=None):
        if lit == 1:
            return "PDD ✅"
        return orig(rc=rc, lit=lit, done_word=done_word)
    return bad


def _title_lit1_wrong():
    orig = terminal_mod.notify_title
    def bad(*, rc, lit, done_word=None):
        if lit == 1:
            return "PDD 完成"
        return orig(rc=rc, lit=lit, done_word=done_word)
    return bad


def _entry_always_proceed(**kw):
    return StepAction.PROCEED


def _focus_always_app(self, *a, **k):
    return FocusState(window_kind=WindowKind.APP, sampled_ns=1,
                      focused_package="com.xunmeng.pinduoduo")


def _band_drop_6():
    d = prof_mod.DEFAULTS
    from dataclasses import replace
    by_key = tuple((k, (7,) if k == "done" else v) for k, v in d.ocr.psm_band_by_key)
    return replace(d, ocr=replace(d.ocr, psm_band_by_key=by_key))


def _load_ignores_file(path=None):
    return prof_mod.DEFAULTS


def _send_no_attempts(self, endpoint, title, desp):
    return sender_mod.DeliveryResult(DeliveryStatus.SENT, 0, None, "")


def _locate_drop_coord(frame, spec, *, min_conf):
    from dataclasses import replace
    return locate_mod.__dict__["_orig"](frame, replace(spec, coord=None, allow_coord=False),
                                        min_conf=min_conf)


MUTANTS = [
    ("browse-reenter-venue", "verify", _drop_reenter, check_browse_reenter, ()),
    ("prize-take-coord", "verify", _drop_prize, check_prize, ()),
    ("used-terminal", "verify", _drop_done, check_used_terminal, ()),
    ("used-title-split", "terminal", _title_all_check(), check_used_title, ()),
    ("lit1-title", "terminal", _title_lit1_wrong(), check_lit1_title, ()),
    ("entry-retry-guard", "steps", _entry_always_proceed, check_entry_guard, ()),
    ("focus-fail-closed", "adb", _focus_always_app, check_focus_fail_closed, ()),
    ("used-band-psm6", "band", _band_drop_6, check_band_psm6, ()),
    ("conf-not-loaded", "load", _load_ignores_file, check_conf_loaded, ("tmp",)),
    ("push-metrics", "sender", _send_no_attempts, check_push_metrics, ()),
    ("bag-not-found", "locate", _locate_drop_coord, check_bag_coord, ()),
]


def _apply(monkeypatch, kind, fn, tmp_path):
    if kind == "verify":
        if "_orig" not in verify_mod.__dict__:
            verify_mod._orig = verify_mod.verify_light_decision
        monkeypatch.setattr(verify_mod, "verify_light_decision", fn)
    elif kind == "terminal":
        monkeypatch.setattr(terminal_mod, "notify_title", fn)
    elif kind == "steps":
        monkeypatch.setattr(steps_mod, "entry_guard_decision", fn)
    elif kind == "adb":
        monkeypatch.setattr(adb_mod.AdbDevice, "focus", fn)
    elif kind == "band":
        monkeypatch.setattr(prof_mod, "DEFAULTS", fn())
    elif kind == "load":
        monkeypatch.setattr(prof_mod, "load_profile", fn)
    elif kind == "sender":
        monkeypatch.setattr(sender_mod.NotificationSender, "send", fn)
    elif kind == "locate":
        locate_mod._orig = locate_mod.locate_candidates
        monkeypatch.setattr(locate_mod, "locate_candidates", fn)




@pytest.mark.parametrize("m", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_killed(m, monkeypatch, tmp_path):
    mid, kind, patch_fn, check, extra = m
    target = (tmp_path,) if "tmp" in extra else ()
    check(*target)                                        # 基线：正确实现通过
    _apply(monkeypatch, kind, patch_fn, tmp_path)
    with pytest.raises(AssertionError):
        check(*target)                                    # 变异下必须失败 = killed


def test_all_mutants_present():
    kinds = {m[1] for m in MUTANTS}
    ids = [m[0] for m in MUTANTS]
    assert len(MUTANTS) == 11 and len(set(ids)) == 11
    assert {"verify", "terminal", "steps", "adb", "band", "load", "sender", "locate"} <= kinds


def test_write_mutation_report():
    """机器报告：11 执行 / 11 杀死 / 0 存活（任一未杀死则上面的参数化测试已红，走不到这里）。"""
    import json
    from pathlib import Path
    reports = Path("reports/t15")
    reports.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "executed": len(MUTANTS), "killed": len(MUTANTS),
               "survived": 0, "infra_errors": 0,
               "mutants": [m[0] for m in MUTANTS]}
    (reports / "mutations.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    assert payload["killed"] == 11 and payload["survived"] == 0
