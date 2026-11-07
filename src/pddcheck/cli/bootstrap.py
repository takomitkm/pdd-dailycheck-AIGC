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
        source = DeviceVisionSource(self._device, self._engine)
        obs = observe_frame(source, frame_id=f"{self._cfg.run_id}-f", capture_id="cap",
                            state_epoch=getattr(self._device, "state_epoch", 0),
                            tap_width=getattr(self._device, "tap_width", 720),
                            tap_height=getattr(self._device, "tap_height", 1280),
                            channels=(CoordinateSource.TESSERACT_PAGE,),
                            xml_policy=xml_policy_for(self._cfg.page_kind))
        self.observe_calls += 1
        results = locate_all(obs, self._cfg.specs, min_conf=40) if self._cfg.specs else {}
        text = "\n".join(obs.ocr_texts.values())
        facts = facts_from_text(text)
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
    deps = RunDeps(device=device, screen=screen, store=store, journal=journal,
                   notifier=notifier, endpoint=cfg.endpoint,
                   evidence_dir=cfg.evidence_dir, business_date=cfg.business_date,
                   run_id=cfg.run_id, now_ns=now_ns, lease_factory=lease_factory,
                   force=cfg.force, close_app_on_ok=cfg.close_app_on_ok)
    outcome = run_once(deps)
    return outcome, {"observe_calls": screen.observe_calls}
