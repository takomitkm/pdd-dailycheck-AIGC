"""组合根（T14/T18a 前）：把真实适配器接成一条可跑的管线。

装配顺序（与 acceptance §5 一致）：设备采集 → 共享观察（observe_frame/locate_all）
→ 事实抽取 → run_once（锁/日标记/点亮/核实/收尾/通知）。
硬件可用 FakeDevice 顶替；真机只需把 device 换成 AdbDevice、engine 换成
TesseractEngine(真实二进制)，其余一行不改——这就是「接线一次、换适配器即可」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pddcheck.domain import CoordinateSource
from pddcheck.notify import NotificationSender
from pddcheck.perception import (
    TargetLocateSpec,
    locate_all,
    observe_frame,
)
from pddcheck.perception.facts import ScreenFacts, facts_from_text
from pddcheck.perception.observe import XmlPolicy, xml_policy_for
from pddcheck.storage import DailyStore, Journal
from pddcheck.vision.engine import OcrEngine
from pddcheck.vision.source import DeviceVisionSource
from pddcheck.workflow.flow import RunDeps, RunOutcome, run_once
from pddcheck.workflow.verify import VerifyObservation, VerifyStage


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    business_date: str
    run_id: str
    evidence_dir: str
    endpoint: str | None
    force: bool = False
    close_app_on_ok: bool = True
    page_kind: str = "activity"
    specs: dict[str, TargetLocateSpec] = field(default_factory=dict)
    # 裁片通道标定（None=不启用该通道；值来自 profile，真机验证见 t18a-calibration-findings）
    pill_box: tuple[float, float, float, float] | None = None
    pill_div: int = 2
    pill_mode: str = "color"
    band_region: tuple[float, float, float, float] | None = None
    band_scale: int = 3
    # 流程段（默认关闭：只做点亮段；开启后先走 就绪→入口→福袋 再读事实）
    # 真机验证见 docs/refactor-v2/t18a-calibration-findings.md
    run_stages: bool = False
    home_activity: str = "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
    entry_retry: int = 2
    prove_max: int = 3
    step_wait_s: float = 4.0
    # 页型驱动的裁片框：{PageKind.value: {key: (box, mode)}}
    pill_by_page: dict[str, dict[str, tuple[tuple[float, float, float, float], str]]] = \
        field(default_factory=dict)


class _ScreenFromPipeline:
    """把「共享观察 + 事实抽取」包成 run_once 需要的 ScreenPort。"""

    def __init__(self, device, engine: OcrEngine, cfg: PipelineConfig) -> None:
        self._device = device
        self._engine = engine
        self._cfg = cfg
        self._before: ScreenFacts | None = None
        self._tap_point = None
        self.last_facts: ScreenFacts | None = None
        self.observe_calls = 0

    def _observe(self) -> tuple[ScreenFacts, object]:
        # 通道选择：整页恒取；有 pill/band 标定的目标才加对应裁片通道
        # （真机实测：频道页「抽福袋」只有 pill color×2 psm7 认得出，整页与 band 都不行）
        channels = [CoordinateSource.TESSERACT_PAGE]
        if self._cfg.pill_box is not None:
            channels.append(CoordinateSource.PILL)
        if self._cfg.band_region is not None:
            channels.append(CoordinateSource.BAND)
        source = DeviceVisionSource(
            self._device, self._engine,
            pill_box=self._cfg.pill_box, pill_div=self._cfg.pill_div,
            pill_mode=self._cfg.pill_mode,
            band_region=self._cfg.band_region, band_scale=self._cfg.band_scale)
        obs = observe_frame(source, frame_id=f"{self._cfg.run_id}-f", capture_id="cap",
                            state_epoch=getattr(self._device, "state_epoch", 0),
                            tap_width=getattr(self._device, "tap_width", 720),
                            tap_height=getattr(self._device, "tap_height", 1280),
                            channels=tuple(channels),
                            xml_policy=xml_policy_for(self._cfg.page_kind))
        self.observe_calls += 1
        results = locate_all(obs, self._cfg.specs, min_conf=40) if self._cfg.specs else {}
        text = "\n".join(obs.ocr_texts.values())
        facts = facts_from_text(text)
        # 裁片通道里认到的 done（整页读不到进度条右侧那个按钮）合并进事实
        done_cand = results.get("done")
        if facts.done_text is None and done_cand is not None and done_cand.winning is not None:
            facts = facts_from_text(text + " 今日已点亮")
        return facts, results

    def light_facts(self) -> dict:
        facts, results = self._observe()
        self.last_facts = facts
        self._before = facts
        light = results.get("light")
        tap_point = light.winning.tap_point if light and light.winning else None
        self._tap_point = tap_point
        return {"done_text": facts.done_text, "exchange_text": facts.exchange_text,
                "pend_text": facts.pend_text, "pend_days": facts.pend_days,
                "before_count": facts.progress_count, "tap_point": tap_point,
                "tap_method": "ocr"}

    def post_tap_observations(self) -> tuple[VerifyObservation, ...]:
        facts_after, _ = self._observe()
        before = self._before.progress_count if self._before else None
        after = facts_after.progress_count
        return (VerifyObservation(VerifyStage.AFTER_DIRECT,
                                  after_count=after,
                                  done_text=facts_after.done_text is not None,
                                  prize_text=facts_after.prize_text is not None,
                                  pend_text=facts_after.pend_text is not None),)


def build_and_run(*, device, engine: OcrEngine, store: DailyStore,
                  notifier: NotificationSender, journal: Journal | None,
                  cfg: PipelineConfig, now_ns, lease_factory=None) -> tuple[RunOutcome, dict]:
    screen = _ScreenFromPipeline(device, engine, cfg)
    stats: dict = {"observe_calls": 0, "stages": []}

    # 流程段（可选）：就绪 → 入口 → 福袋；失败以 StageFailure 带 rc 收手，
    # 由 run_once 映射成 4/5/7（不写标记、只 HOME 收尾）。
    if cfg.run_stages:
        from pddcheck.workflow.stages import (
            StageFailure, StagePolicy, StageRunner,
        )
        policy = StagePolicy(pkg="com.xunmeng.pinduoduo", home_activity=cfg.home_activity,
                             entry_retry=cfg.entry_retry, prove_max=cfg.prove_max,
                             step_wait_s=cfg.step_wait_s)

        def act(kind, point):
            from pddcheck.domain import ActionIntent, ActionKind, WindowKind
            mapping = {"tap": ActionKind.TAP, "back": ActionKind.BACK, "start": ActionKind.START,
                       "wake": ActionKind.WAKE, "dismiss_keyguard": ActionKind.DISMISS_KEYGUARD,
                       "swipe": ActionKind.SWIPE}
            k = mapping[kind]
            business = k in (ActionKind.TAP, ActionKind.BACK, ActionKind.SWIPE)
            intent = ActionIntent(
                action_id=f"{cfg.run_id}-{kind}-{now_ns()}",
                run_id=cfg.run_id, kind=k, source_capture_id="stage",
                state_epoch=getattr(device, "state_epoch", 0), geometry_revision=0,
                deadline_ns=now_ns() + 30_000_000_000, reason=f"stage {kind}",
                source_candidate_id=("stage-cand" if business else None),
                target_key=("stage" if business else None),
                expected_package=("com.xunmeng.pinduoduo" if business else None),
                required_window_kind=(WindowKind.APP if business else None))
            return device.execute(intent, point)

        def read_page():
            from pddcheck.workflow.stages import PageView
            # 必须保留**完整 OCR 文本**（不是只留 facts 字段）：流程段要用它定位
            # 「百亿补贴」「抽福袋」等控件文本。
            from pddcheck.domain import CoordinateSource
            from pddcheck.perception import observe_frame, parse_tsv
            src = DeviceVisionSource(
                device, engine, pill_box=cfg.pill_box, pill_div=cfg.pill_div,
                pill_mode=cfg.pill_mode)
            obs = observe_frame(src, frame_id=f"{cfg.run_id}-s", capture_id="stage",
                                state_epoch=getattr(device, "state_epoch", 0),
                                tap_width=getattr(device, "tap_width", 720),
                                tap_height=getattr(device, "tap_height", 1280),
                                channels=(CoordinateSource.TESSERACT_PAGE,),
                                xml_policy=XmlPolicy.SKIP)
            stats["observe_calls"] += 1
            text = " ".join(ln.normalized_text
                            for ln in parse_tsv("\n".join(obs.ocr_texts.values())))
            fs = device.focus()
            return PageView(fs.focused_package, fs.focused_activity, text)

        runner = StageRunner(read_page, act, policy)
        try:
            runner.ensure_ready()
            stats["stages"].append("ready:ok")
            runner.enter_subsidy(cfg.specs["subsidy"], scroll_to_top=runner.scroll_to_top)
            stats["stages"].append("entry:ok")
            runner.open_bag(cfg.specs["bag"])
            stats["stages"].append("bag:ok")
        except StageFailure as exc:
            stats["stages"].append(f"failed:rc{exc.rc}")
            stats["stage_failure"] = exc.why
            stats["stage_failure_rc"] = exc.rc
        except KeyError as exc:                     # specs 缺键=配置错误，直接报
            stats["stages"].append(f"config_error:{exc}")

    deps = RunDeps(device=device, screen=screen, store=store, journal=journal,
                   notifier=notifier, endpoint=cfg.endpoint,
                   evidence_dir=cfg.evidence_dir, business_date=cfg.business_date,
                   run_id=cfg.run_id, now_ns=now_ns, lease_factory=lease_factory,
                   force=cfg.force, close_app_on_ok=cfg.close_app_on_ok,
                   stage_failure_rc=stats.get("stage_failure_rc"),
                   stage_failure_why=stats.get("stage_failure"))
    outcome = run_once(deps)
    stats["observe_calls"] = screen.observe_calls
    return outcome, stats
