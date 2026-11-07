"""T15 共享：把场景字典喂进 run_once（Fake 全注入，无真 sleep）。"""

from __future__ import annotations

from pddcheck.device import FakeDevice
from pddcheck.notify import NotificationSender
from pddcheck.storage import DailyStore, Journal, LockBusy
from pddcheck.workflow.flow import RunDeps, run_once
from pddcheck.workflow.verify import VerifyObservation, VerifyStage

OK = NotificationSender(transport=lambda u, t: (200, '{"code": 0}'))


class Screen:
    def __init__(self, facts, obs=()):
        self._f = dict(facts)
        self._o = tuple(obs)

    def light_facts(self):
        return dict(self._f)

    def post_tap_observations(self):
        return self._o


def run_case(tmp_path, *, facts=None, obs=(), marker=False, force=False,
             lock_busy=False, failures=(), ledger_seed=None, endpoint="http://stub/x"):
    dev = FakeDevice(now_ns=lambda: 1000)
    for f in failures:
        dev.inject_failure(f)
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    if ledger_seed is not None:
        store.ledger_write(ledger_seed)
    if marker:
        store.write_marker("2026-11-07")
    lease = None
    if lock_busy:
        def lease():
            raise LockBusy("busy")
    deps = RunDeps(
        device=dev, screen=Screen(facts or {}, obs), store=store,
        journal=Journal(tmp_path / "j.jsonl"), notifier=OK, endpoint=endpoint,
        evidence_dir=str(tmp_path / "ev"), business_date="2026-11-07",
        run_id="run-1", now_ns=lambda: 1000, lease_factory=lease, force=force)
    return run_once(deps), dev, store


def after(n):
    return (VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=n),)


def after_popup(**kw):
    return (VerifyObservation(VerifyStage.AFTER_POPUP, **kw),)
