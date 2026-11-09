"""迁移审计 G4/G8/G9：终态效果执行（final_scroll / close_policy / last_activity / prune）。

背景：terminal_plan 早就算出 final_scroll 与 close_policy，但执行器只把它们当
字符串写进 RunOutcome、从不真正下发——跑成功既不关 app、也不做 I06 要求的
最终 20 次下滑。本文件把「计划 → 真的下发」钉死（默认关，CLI 真机路径开）。
"""

from __future__ import annotations

import os

from pddcheck.device import FakeDevice
from pddcheck.notify import NotificationSender
from pddcheck.storage import DailyStore, Journal
from pddcheck.workflow.flow import RunDeps, run_once
from pddcheck.workflow.verify import VerifyObservation, VerifyStage


class RecordingDevice:
    """包一层 FakeDevice，把 (kind, point) 也记下来——FakeDevice.execute 不存 point。"""

    def __init__(self, dev: FakeDevice) -> None:
        self._dev = dev
        self.actions: list[tuple[str, tuple[int, ...] | None]] = []

    def execute(self, intent, point=None):
        self.actions.append((intent.kind.value, point))
        return self._dev.execute(intent, point)

    def focus(self):
        return self._dev.focus()

    @property
    def state_epoch(self):
        return self._dev.state_epoch

    @property
    def tap_width(self):
        return self._dev.tap_width

    @property
    def tap_height(self):
        return self._dev.tap_height


class Screen:
    def __init__(self, facts, obs=()):
        self._f = dict(facts)
        self._o = tuple(obs)

    def light_facts(self):
        return dict(self._f)

    def post_tap_observations(self):
        return self._o


def sender(status=200, body='{"code": 0}'):
    return NotificationSender(transport=lambda url, t: (status, body))


def deps(tmp_path, *, facts=None, obs=(), effects=False, dry_run=False,
         keep_days=7, browse_sleep=None):
    dev = FakeDevice(now_ns=lambda: 1000, tap_size=(720, 1280))
    rec = RecordingDevice(dev)
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    d = RunDeps(
        device=rec, screen=Screen(facts or {}, obs), store=store,
        journal=Journal(tmp_path / "journal" / "a.jsonl"), notifier=sender(),
        endpoint="http://stub/send", evidence_dir=str(tmp_path / "runs" / "d"),
        business_date="2026-11-07", run_id="run-1", now_ns=lambda: 1000,
        lease_factory=None, force=False,
        dry_run=dry_run, browse_sleep=browse_sleep,
        execute_terminal_effects=effects, keep_days=keep_days)
    return d, rec, store


SUCCESS = {"before_count": 4, "tap_point": (100, 900), "tap_method": "ocr"}
SUCCESS_OBS = (VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=3),)
RC6_OBS = (VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=4),)


# --------------------------------------------------------------- G4 final_scroll


def test_success_runs_final_scroll_then_stop_and_home(tmp_path):
    """I06：rc0&lit3 → 最终 20 次下滑（300ms、比例口径）→ force-stop + HOME。"""
    d, rec, _ = deps(tmp_path, facts=SUCCESS, obs=SUCCESS_OBS, effects=True,
                     browse_sleep=lambda s: None)
    out = run_once(d)
    assert out.exit_code.value == 0 and out.lit == 3
    kinds = [k for k, _ in rec.actions]
    assert kinds.count("swipe") == 20                    # 最终 20 次下滑
    assert kinds[-2:] == ["stop", "home"]                # rc0：force-stop + HOME
    swipe_points = [p for k, p in rec.actions if k == "swipe"]
    # 比例口径（720x1280）：x=540、y1=1200、y2=700、按压 300ms
    assert all(p == (540, 1200, 540, 700, 300) for p in swipe_points)


def test_rc6_only_home_no_final_scroll_no_stop(tmp_path):
    """rc≠0 收尾只有 HOME（B07：不 force-stop），绝不做最终下滑。"""
    d, rec, _ = deps(tmp_path, facts=SUCCESS, obs=RC6_OBS, effects=True,
                     browse_sleep=lambda s: None)
    out = run_once(d)
    assert out.rc == 6 and not out.marker_written
    kinds = [k for k, _ in rec.actions]
    assert "swipe" not in kinds
    assert kinds == ["tap", "home"]


def test_lit2_and_lit4_stay_no_terminal_actions(tmp_path):
    """lit2/4：手机停在当前屏等她，一个键都不放（I02/I13）。"""
    d2, rec2, _ = deps(tmp_path, facts={"exchange_text": "立即兑换"}, effects=True)
    out2 = run_once(d2)
    assert out2.lit == 2 and out2.close_policy == "stay"
    assert rec2.actions == []
    d4, rec4, _ = deps(tmp_path, facts={"pend_text": "待兑换", "pend_days": 3},
                       effects=True)
    out4 = run_once(d4)
    assert out4.lit == 4 and out4.close_policy == "stay"
    assert rec4.actions == []


def test_baseline_default_off_keeps_47case_behaviour(tmp_path):
    """47 案基线：不开 execute_terminal_effects 时不下发任何终态动作。"""
    d, rec, _ = deps(tmp_path, facts=SUCCESS, obs=SUCCESS_OBS, effects=False)
    out = run_once(d)
    assert out.exit_code.value == 0 and out.lit == 3
    assert out.close_policy == "stop_and_home"           # 计划照算
    assert [k for k, _ in rec.actions] == ["tap"]        # 但不下发


def test_dry_run_never_executes_terminal_actions(tmp_path):
    """纯观察：识别与决策照做，终态动作一个不发。"""
    d, rec, _ = deps(tmp_path, facts=SUCCESS, obs=SUCCESS_OBS, effects=True,
                     dry_run=True)
    out = run_once(d)
    assert rec.actions == []
    assert "dry-run" in " ".join(out.notes)


# --------------------------------------------------------------- G8 last_activity


def test_rc6_body_carries_last_activity(tmp_path):
    """G8：关 app 前读焦点，推送正文里的「最后停在 X 这一屏」不再是读不到。"""
    d, rec, _ = deps(tmp_path, facts=SUCCESS, obs=RC6_OBS, effects=True)
    out = run_once(d)
    # FakeDevice 默认 activity="HomeActivity"（短名即可断言，正文原样带出）
    assert "最后停在 HomeActivity 这一屏" in out.body


def test_rc6_body_falls_back_to_du_bu_dao(tmp_path):
    """焦点读不出时照旧「读不到」（旧口径），不阻塞收尾。"""

    class NoFocusDevice(RecordingDevice):
        def focus(self):
            raise RuntimeError("focus lost")

    dev = FakeDevice(now_ns=lambda: 1000, tap_size=(720, 1280))
    rec = NoFocusDevice(dev)
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    d = RunDeps(device=rec, screen=Screen(dict(SUCCESS), RC6_OBS), store=store,
                journal=None, notifier=sender(), endpoint=None,
                evidence_dir=str(tmp_path / "runs" / "d"),
                business_date="2026-11-07", run_id="run-1", now_ns=lambda: 1000,
                lease_factory=None, execute_terminal_effects=True)
    out = run_once(d)
    assert out.rc == 6
    assert "最后停在 读不到 这一屏" in out.body
    assert [k for k, _ in rec.actions] == ["tap", "home"]   # 收尾不受影响


# --------------------------------------------------------------- G9 prune


def test_flow_prunes_expired_evidence_dirs(tmp_path):
    """G9：keep_days 到了删过期日期目录；marker 文件与新目录不动。"""
    d, rec, store = deps(tmp_path, facts=SUCCESS, obs=SUCCESS_OBS, effects=True,
                         keep_days=7, browse_sleep=lambda s: None)
    root = store.evidence_root
    old = root / "2026-01-01"
    fresh = root / "2026-11-07"
    old.mkdir(parents=True)
    fresh.mkdir(parents=True)
    old_ts = 1_000_000_000                                # 2001 年，必过期
    os.utime(old, (old_ts, old_ts))
    run_once(d)
    assert not old.exists()
    assert fresh.exists()                                 # 当天目录保留
    assert (root / ".done-2026-11-07").exists()           # 标记文件不是目录，不动


def test_flow_without_effects_does_not_prune(tmp_path):
    """47 案基线：不开终态效果时也不做证据清理。"""
    d, rec, store = deps(tmp_path, facts=SUCCESS, obs=SUCCESS_OBS, effects=False,
                         keep_days=7)
    root = store.evidence_root
    old = root / "2026-01-01"
    old.mkdir(parents=True)
    os.utime(old, (1_000_000_000, 1_000_000_000))
    run_once(d)
    assert old.exists()


def test_prune_zero_keep_days_is_noop(tmp_path):
    d, rec, store = deps(tmp_path, facts=SUCCESS, obs=SUCCESS_OBS, effects=True,
                         keep_days=0)
    old = store.evidence_root / "2026-01-01"
    old.mkdir(parents=True)
    os.utime(old, (1_000_000_000, 1_000_000_000))
    run_once(d)
    assert old.exists()                                   # keep_days=0 不清理
