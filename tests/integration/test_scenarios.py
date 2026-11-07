"""T15(1/2)：fixture 驱动的场景表——精确 trace、FakeClock 无真 sleep。

每个场景声明输入（屏事实/核实观察/设备故障/标记/force）与期望
（退出码/lit/marker/账本/收尾/标题/实际执行动作数）。跑 run_once 断言全字段，
不是只断次数。表格式对齐旧 47 用例的关键分类，D 表差异单列。
"""

from __future__ import annotations

import pytest

from pddcheck.cli.exits import ExitCode
from pddcheck.device import FakeDevice
from pddcheck.notify import NotificationSender
from pddcheck.storage import DailyStore, Journal
from pddcheck.workflow.flow import RunDeps, run_once
from pddcheck.workflow.verify import VerifyObservation, VerifyStage

OK_SENDER = NotificationSender(transport=lambda u, t: (200, '{"code": 0}'))


class Screen:
    def __init__(self, facts, obs=()):
        self._f = dict(facts)
        self._o = tuple(obs)

    def light_facts(self):
        return dict(self._f)

    def post_tap_observations(self):
        return self._o


def _run(tmp_path, case):
    dev = FakeDevice(now_ns=lambda: 1000)
    for f in case.get("failures", []):
        dev.inject_failure(f)
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    if case.get("marker"):
        store.write_marker("2026-11-07")
    lease = None
    if case.get("lock_busy"):
        from pddcheck.storage import LockBusy
        def lease():
            raise LockBusy("busy")
    deps = RunDeps(
        device=dev, screen=Screen(case.get("facts", {}), case.get("obs", ())),
        store=store, journal=Journal(tmp_path / "j.jsonl"), notifier=OK_SENDER,
        endpoint="http://stub/x", evidence_dir=str(tmp_path / "ev"),
        business_date="2026-11-07", run_id="run-1", now_ns=lambda: 1000,
        lease_factory=lease, force=case.get("force", False))
    return run_once(deps), dev


def obs_after(n):
    return (VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=n),)


PAID = {"before_count": 4, "tap_point": (100, 900)}

CASES = [
    dict(name="marker_skip", marker=True, facts={},
         expect=dict(code=ExitCode.OK, lit=None, skipped="daily_marker", executed=0)),
    dict(name="force_done_lit1", marker=True, force=True,
         facts={"done_text": "今日已点亮"},
         expect=dict(code=ExitCode.OK, lit=1, marker=True, ledger=0, close="stop_and_home",
                     executed=0, title="PDD ✅")),
    dict(name="exchange_lit2", facts={"exchange_text": "立即兑换", "before_count": 4},
         expect=dict(code=ExitCode.OK, lit=2, marker=False, ledger=0, close="stay",
                     executed=0, title="PDD 需人工")),
    dict(name="pend_lit4", facts={"pend_text": "待兑换", "pend_days": 2},
         expect=dict(code=ExitCode.OK, lit=4, marker=True, ledger=2, close="stay",
                     executed=0, title="PDD 💡")),
    dict(name="lit3_counter_decrease", facts=PAID, obs=obs_after(3),
         expect=dict(code=ExitCode.OK, lit=3, marker=True, ledger=0, close="stop_and_home",
                     executed=1, title="PDD ✅")),
    dict(name="rc6_counter_unchanged", facts=PAID, obs=obs_after(4),
         expect=dict(code=ExitCode.LIGHT_NOT_APPLIED, lit=None, marker=False,
                     close="home_only", executed=1, title="PDD ⬛ 退出码 6")),
    dict(name="rc6_prize_overlay", facts=PAID,
         obs=(VerifyObservation(VerifyStage.AFTER_POPUP, prize_text=True),),
         expect=dict(code=ExitCode.OK, lit=3, marker=True, executed=1)),
    dict(name="unknown_execution_no_retry", facts=PAID, failures=["lost_response"],
         expect=dict(code=ExitCode.LIGHT_NOT_APPLIED, lit=None, marker=False, executed=1)),
    dict(name="lock_busy", lock_busy=True, facts={},
         expect=dict(code=ExitCode.LOCK_BUSY, skipped="lock_busy", executed=0)),
]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_scenario(tmp_path, case):
    out, dev = _run(tmp_path, case)
    e = case["expect"]
    assert out.exit_code is e["code"], f"{case['name']}: exit {out.exit_code} != {e['code']}"
    if "lit" in e:
        assert out.lit == e["lit"], f"{case['name']}: lit {out.lit} != {e['lit']}"
    if "skipped" in e:
        assert out.skipped == e["skipped"]
    if "marker" in e:
        assert out.marker_written is e["marker"], f"{case['name']}: marker"
    if "ledger" in e:
        assert out.ledger_written == e["ledger"], f"{case['name']}: ledger"
    if "close" in e:
        assert out.close_policy == e["close"], f"{case['name']}: close {out.close_policy}"
    if "title" in e:
        assert out.title == e["title"], f"{case['name']}: title {out.title}"
    assert len(dev.executed) == e.get("executed", len(dev.executed)), \
        f"{case['name']}: executed {len(dev.executed)} != {e.get('executed')}"


def test_marker_write_failure_is_73_but_keeps_business_rc(tmp_path):
    """D04：业务成功但 marker 写入失败 → 进程码 73，业务 rc 保留，绝不虚称已写。"""
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    # 把证据目录变成一个文件，使 marker 的 mkdir 失败
    (tmp_path / "runs").write_text("blocker", encoding="utf-8")
    deps = RunDeps(
        device=FakeDevice(now_ns=lambda: 1000),
        screen=Screen({"done_text": "今日已点亮"}), store=store,
        journal=Journal(tmp_path / "j.jsonl"), notifier=OK_SENDER,
        endpoint=None, evidence_dir=str(tmp_path / "ev"),
        business_date="2026-11-07", run_id="r", now_ns=lambda: 1000)
    out = run_once(deps)
    assert out.exit_code is ExitCode.STATE_DIR_FAILED
    assert out.marker_written is False
    assert out.lit == 1                         # 业务结果仍可见
    assert any("business_rc=" in n for n in out.notes)


def test_scenarios_never_real_sleep(tmp_path):
    """整表跑完远小于真实 sleep 的量级——证明没有真 sleep（FakeClock）。
    阈值 5s：9 个场景含文件写入，机器负载高时也可能到 1-2s；重点是「不是分钟级 sleep」。"""
    import time
    t0 = time.monotonic()
    for case in CASES:
        _run(tmp_path / case["name"], case)
    assert time.monotonic() - t0 < 5.0
