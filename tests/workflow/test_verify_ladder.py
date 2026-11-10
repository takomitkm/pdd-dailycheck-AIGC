"""迁移审计 G1/G2/G3/G5：verify 四阶段阶梯真执行。

旧 pdd.sh verify_light（L1299-1389）的顺序：
  浏览滑完 → BACK 离开消费页 → 落点读进度（AFTER_BACK）
           → 落频道页认到「抽福袋」再点回活动页（AFTER_REENTER）
           → 读不到进度：清浮层（认到关闭词才点）再读（AFTER_POPUP）
           → 奖励浮层在场：点「开心收下」收奖（PRIZE 分支才允许 take）
本文件用脚本化 Screen（按 stage 返回观察 + locate_target 给点）驱动，
用 RecordingDevice 断言真的下发了 BACK / 胶囊点 / 收奖点。
"""

from __future__ import annotations

from pddcheck.device import FakeDevice
from pddcheck.notify import NotificationSender
from pddcheck.storage import DailyStore, Journal
from pddcheck.workflow import flow as flowmod
from pddcheck.workflow.flow import RunDeps, run_once
from pddcheck.workflow.verify import VerifyObservation, VerifyStage, verify_light_decision

PKG = "com.xunmeng.pinduoduo"


class RecordingDevice:
    def __init__(self):
        self._dev = FakeDevice(now_ns=lambda: 1000, tap_size=(720, 1280))
        self.actions: list[tuple[str, object]] = []

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


class LadderScreen:
    """按 stage 返回预设观察；locate_target 返回预设点。"""

    def __init__(self, facts, obs_by_stage, locs=None):
        self._facts = dict(facts)
        self._obs = dict(obs_by_stage)      # VerifyStage -> VerifyObservation
        self._locs = dict(locs or {})
        self.posted_stages: list[VerifyStage] = []

    def light_facts(self):
        return dict(self._facts)

    def post_tap_observations(self, stage=VerifyStage.AFTER_DIRECT):
        self.posted_stages.append(stage)
        return (self._obs.get(stage, VerifyObservation(stage)),)

    def locate_target(self, key):
        return self._locs.get(key)


def sender():
    return NotificationSender(transport=lambda url, t: (200, '{"code": 0}'))


def deps(tmp_path, screen, *, verify_ladder=True, browse_after_light=False):
    store = DailyStore(tmp_path / "runs", tmp_path / "pause")
    rec = RecordingDevice()
    d = RunDeps(
        device=rec, screen=screen, store=store,
        journal=Journal(tmp_path / "j.jsonl"), notifier=sender(),
        endpoint=None, evidence_dir=str(tmp_path / "ev"),
        business_date="2026-11-07", run_id="run-1", now_ns=lambda: 1000,
        lease_factory=None, browse_after_light=browse_after_light,
        browse_sleep=lambda s: None, verify_ladder=verify_ladder,
        execute_terminal_effects=False)     # 隔离：本文件只关心 verify 动作
    return d, rec


FACTS = {"before_count": 4, "tap_point": (100, 900), "tap_method": "ocr"}


# --------------------------------------------------------------- G5 done / popup


def test_ladder_direct_unreadable_then_popup_done_is_lit3(tmp_path):
    """原地读不到进度 → 认到浮层关闭词点掉 → 复读到「已点亮」→ lit3（非弱证明）。"""
    scr = LadderScreen(
        FACTS,
        {VerifyStage.AFTER_DIRECT: VerifyObservation(VerifyStage.AFTER_DIRECT),
         VerifyStage.AFTER_POPUP: VerifyObservation(VerifyStage.AFTER_POPUP, done_text=True)},
        locs={"popup": (600, 300)})
    d, rec = deps(tmp_path, scr)
    out = run_once(d)
    assert out.exit_code.value == 0 and out.lit == 3
    kinds = [k for k, _ in rec.actions]
    assert "tap" in kinds                                    # 点亮那一枪
    assert ("tap", (600, 300)) in rec.actions                # 点掉浮层
    assert VerifyStage.AFTER_POPUP in scr.posted_stages


def test_ladder_counter_unchanged_is_rc6(tmp_path):
    """阶梯跑完进度没变小 → rc6（绝不误报成功）。"""
    scr = LadderScreen(
        FACTS,
        {VerifyStage.AFTER_DIRECT: VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=4)})
    d, rec = deps(tmp_path, scr)
    out = run_once(d)
    assert out.exit_code.value == 6 and out.rc == 6
    assert not out.marker_written


# --------------------------------------------------------------- G3 prize take


def test_ladder_prize_branch_taps_take(tmp_path):
    """进度读不到 + 奖励浮层在场 → 判定 PRIZE(lit3) 并点「开心收下」收奖。"""
    scr = LadderScreen(
        FACTS,
        {VerifyStage.AFTER_DIRECT: VerifyObservation(VerifyStage.AFTER_DIRECT),
         VerifyStage.AFTER_POPUP: VerifyObservation(VerifyStage.AFTER_POPUP, prize_text=True,
                                                    take_point=(359, 752))})
    d, rec = deps(tmp_path, scr)
    out = run_once(d)
    assert out.exit_code.value == 0 and out.lit == 3
    assert ("tap", (359, 752)) in rec.actions               # 真的点了收奖
    assert any("开心收下" in n for n in out.notes)


def test_no_take_without_prize_branch(tmp_path):
    """非奖励浮层分支绝不许借 take 点（契约 L197）——进度正常变小时不点收奖。"""
    scr = LadderScreen(
        FACTS,
        {VerifyStage.AFTER_DIRECT: VerifyObservation(VerifyStage.AFTER_DIRECT, after_count=3,
                                                     take_point=(359, 752))})
    d, rec = deps(tmp_path, scr)
    out = run_once(d)
    assert out.lit == 3
    assert ("tap", (359, 752)) not in rec.actions


# --------------------------------------------------------------- G2 browse BACK/reenter


def test_verify_after_light_browsed_backs_then_reads(tmp_path):
    """G2：browsed=True → 先 BACK（device 收到 back），AFTER_BACK 读到进度即停。"""
    scr = LadderScreen(
        FACTS,
        {VerifyStage.AFTER_BACK: VerifyObservation(VerifyStage.AFTER_BACK, after_count=3)})
    d, rec = deps(tmp_path, scr)
    obs = flowmod._verify_after_light(d, [], browsed=True, verify_ladder=True)
    kinds = [k for k, _ in rec.actions]
    assert kinds == ["back"]                                 # 滑完必按 BACK（旧 L1317）
    decision = verify_light_decision(4, "ocr", obs)
    assert decision.rc == 0 and decision.lit == 3


def test_verify_after_light_browsed_landing_bag_then_reenter(tmp_path):
    """G2：BACK 落频道页读不到进度，但认到「抽福袋」胶囊 → 点回活动页再读（AFTER_REENTER）。"""
    scr = LadderScreen(
        FACTS,
        {VerifyStage.AFTER_BACK: VerifyObservation(VerifyStage.AFTER_BACK),          # 频道页无进度
         VerifyStage.AFTER_REENTER: VerifyObservation(VerifyStage.AFTER_REENTER, after_count=2)},
        locs={"bag": (435, 524)})
    d, rec = deps(tmp_path, scr)
    obs = flowmod._verify_after_light(d, [], browsed=True, verify_ladder=True)
    kinds = [k for k, _ in rec.actions]
    assert kinds == ["back", "tap"]                          # BACK 后点胶囊回活动页
    assert ("tap", (435, 524)) in rec.actions
    decision = verify_light_decision(4, "ocr", obs)
    assert decision.rc == 0 and decision.lit == 3 and decision.proof_kind.value == "counter_decrease"


def test_verify_after_light_landing_bag_not_found_does_not_blind_tap(tmp_path):
    """G2 安全半边：落点认不到「抽福袋」→ 绝不盲点（10-11 rc=5 教训），只 BACK。"""
    scr = LadderScreen(
        FACTS,
        {VerifyStage.AFTER_BACK: VerifyObservation(VerifyStage.AFTER_BACK)},        # 无进度
        locs={})                                                 # 认不到 bag
    d, rec = deps(tmp_path, scr)
    flowmod._verify_after_light(d, [], browsed=True, verify_ladder=True)
    kinds = [k for k, _ in rec.actions]
    assert kinds == ["back"]                                 # 绝不盲点坐标
    assert not any(k == "tap" for k, _ in rec.actions)


# --------------------------------------------------------------- 基线不受影响


def test_baseline_ladder_off_single_observation(tmp_path):
    """47 案基线：verify_ladder=False → 只调一次 post_tap_observations（不传 stage）。"""
    scr = LadderScreen(FACTS, {VerifyStage.AFTER_DIRECT: VerifyObservation(
        VerifyStage.AFTER_DIRECT, after_count=3)})
    d, rec = deps(tmp_path, scr, verify_ladder=False)
    run_once(d)
    assert scr.posted_stages == [VerifyStage.AFTER_DIRECT]   # 只读一次
    assert [k for k, _ in rec.actions] == ["tap"]            # 只有点亮那一枪
