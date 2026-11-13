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
    # 冷启动入口（旧脚本 HOME_ACT=MainFrameActivity；`am start -n 包名/Activity`）。
    # 与 home_activity（「已在首页」匹配口径=HomeActivity）分开——11-10 rc7 的根因是
    # 把裸类名塞给 am start -n（缺包名前缀），冷启动从来没成功过。
    launch_activity: str = "com.xunmeng.pinduoduo.ui.activity.MainFrameActivity"
    entry_retry: int = 2
    prove_max: int = 3
    step_wait_s: float = 4.0
    # 频道页「抽福袋」的裁片标定（ADR-003 候选值，真机实测 (435,524)）：
    # (box, mode)；None=不启用（open_bag 就只用整页 OCR，频道页会 rc5）
    bag_pill: tuple[tuple[float, float, float, float], str] | None = None
    pill_div: int = 2
    pill_th: int = 120
    # light/done 的右上按钮裁片（profile [targets.light].pill 同值；整页读不出）
    light_pill: tuple[tuple[float, float, float, float], str] | None = None
    # 点亮后浏览任务段（滑动 10s 才真点亮）；CLI 真机路径开、47 案基线关
    browse_after_light: bool = False
    # 终态效果执行（迁移审计 G4/G8）：final_scroll（I06）+ close_policy 下发 +
    # last_activity 采集；CLI 真机路径开、47 案基线关
    execute_terminal_effects: bool = False
    # verify 四阶段阶梯真执行（G1/G2/G3/G5）：browse→BACK→reconcile + 清浮层复读 +
    # 奖励浮层点「开心收下」；CLI 真机路径开、47 案基线关
    verify_ladder: bool = False
    # 入口锚点（11-13 加固）：首页「百亿补贴」是艺术字（OCR 读不稳），改用
    # **可读图标行文字** + 偏移推算候选点。认不到锚点 → 不点（绝不盲点）。
    entry_anchor_labels: tuple[str, ...] = ("限时秒杀", "充值中心", "免费领礼物", "多多果园")
    # (dx, dy) 屏幕比例，相对锚点文字框左上角；多组 = 多个候选（逐个试点 + 落地校验）。
    # 11-13 实测：锚点「限时秒杀」文字 x=36..109 y=452..469；百亿补贴图标区
    # x≈30..120 y≈680..790 → dx≈0（与图标行同列），dy≈0.18~0.26（商品行高度会变）。
    entry_anchor_offsets: tuple[tuple[float, float], ...] = (
        (0.0, 0.20), (0.0, 0.26), (0.02, 0.23), (0.0, 0.14),
    )
    # 纯观察：识别与决策照做，业务动作一律拒绝、不写标记/账本、不推送（只留证据）
    dry_run: bool = False


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
        # light/done 裁片通道（profile [targets.light].pill 已有真机验证值；
        # 整页 OCR 读不出「立即点亮/今日已点亮」——进度条右侧的按钮）
        self._light_pill = getattr(cfg, "light_pill", None)

    def _observe(self) -> tuple[ScreenFacts, object]:
        # 通道选择：整页恒取两档（稀疏 psm11 先、整页 psm6 后——旧脚本 L824 同序）；
        # 有 pill/band 标定的目标才加对应裁片通道
        # （真机实测：频道页「抽福袋」只有 pill color×2 psm7 认得出，整页与 band 都不行）。
        channels = [CoordinateSource.TESSERACT_SPARSE, CoordinateSource.TESSERACT_PAGE]
        if self._cfg.pill_box is not None:
            channels.append(CoordinateSource.PILL)
        if self._cfg.band_region is not None:
            channels.append(CoordinateSource.BAND)
        if self._light_pill is not None:
            channels.append(CoordinateSource.PILL_LIGHT)
        source = DeviceVisionSource(
            self._device, self._engine,
            pill_box=self._cfg.pill_box, pill_div=self._cfg.pill_div,
            pill_mode=self._cfg.pill_mode,
            band_region=self._cfg.band_region, band_scale=self._cfg.band_scale,
            light_pill=self._light_pill)
        obs = observe_frame(source, frame_id=f"{self._cfg.run_id}-f", capture_id="cap",
                            state_epoch=getattr(self._device, "state_epoch", 0),
                            tap_width=getattr(self._device, "tap_width", 720),
                            tap_height=getattr(self._device, "tap_height", 1280),
                            channels=tuple(channels),
                            xml_policy=xml_policy_for(self._cfg.page_kind))
        self.observe_calls += 1
        results = locate_all(obs, self._cfg.specs, min_conf=40) if self._cfg.specs else {}
        text = "\n".join(obs.ocr_texts.values())
        self._last_raw_text = text          # 浏览页判定用（facts 字段不含任务条文案）
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
        # 浏览页判定（生产 11-08 晚）：整页文本含「滑动浏览」+「即可点亮」→ 已在浏览任务页
        page_text = " ".join(str(v) for v in
                             (facts.done_text, facts.exchange_text, facts.pend_text)) or ""
        all_text = getattr(self, "_last_raw_text", "")
        browse_page = ("滑动浏览" in all_text and "即可点亮" in all_text)
        return {"done_text": facts.done_text, "exchange_text": facts.exchange_text,
                "pend_text": facts.pend_text, "pend_days": facts.pend_days,
                "before_count": facts.progress_count, "tap_point": tap_point,
                "tap_method": "ocr", "browse_page": browse_page}

    def post_tap_observations(self, stage: VerifyStage = VerifyStage.AFTER_DIRECT
                              ) -> tuple[VerifyObservation, ...]:
        facts_after, results = self._observe()
        after = facts_after.progress_count
        # G3：奖励浮层在场 → 定位「开心收下」（旧 take_prize_overlay）。整页读不到它
        # （pdd.sh L106-107：只有裁片档读得出），所以认不到字就退配置中心（分数=0 也点，
        # 但**只有奖励浮层证明分支**会拿这个点——契约 L197）。
        take_point = None
        if facts_after.prize_text is not None:
            take_point = self._take_point(results)
        return (VerifyObservation(stage,
                                  after_count=after,
                                  done_text=facts_after.done_text is not None,
                                  prize_text=facts_after.prize_text is not None,
                                  pend_text=facts_after.pend_text is not None,
                                  take_point=take_point),)

    def _take_point(self, results) -> tuple[int, int] | None:
        """「开心收下」点击点：认到字优先，认不到退配置中心（旧 COORD_take 口径）。"""
        r = results.get("take")
        if r is not None and r.winning is not None and r.winning.tap_point is not None:
            return r.winning.tap_point
        spec = self._cfg.specs.get("take")
        if spec is None or spec.coord is None:
            return None
        tw = int(getattr(self._device, "tap_width", 0) or 720)
        th = int(getattr(self._device, "tap_height", 0) or 1280)
        return (int(spec.coord[0] * tw), int(spec.coord[1] * th))

    def locate_target(self, key: str) -> tuple[int, int] | None:
        """G1/G2/G5：当前帧定位某目标（bag 胶囊 / popup 关闭词）。认不到字 → None。

        语义与旧 text_present 一致：**不收坐标兜底**（认不到字就是认不到，绝不盲点——
        10-11 的 rc=5 就是盲点坐标惹的）。
        """
        _, results = self._observe()
        r = results.get(key)
        if r is not None and r.winning is not None and r.winning.tap_point is not None:
            return r.winning.tap_point
        return None


def _write_tmp_png(data: bytes):
    import tempfile
    from pathlib import Path
    fh = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fh.write(data)
    fh.close()
    return Path(fh.name)


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
            from pddcheck.domain import (
                ActionIntent, ActionKind, ActionReceipt, ExecutionStatus, WindowKind,
            )
            mapping = {"tap": ActionKind.TAP, "back": ActionKind.BACK, "start": ActionKind.START,
                       "wake": ActionKind.WAKE, "dismiss_keyguard": ActionKind.DISMISS_KEYGUARD,
                       "swipe": ActionKind.SWIPE, "stop": ActionKind.STOP}
            k = mapping[kind]
            business = k in (ActionKind.TAP, ActionKind.BACK, ActionKind.SWIPE)
            action_id = f"{cfg.run_id}-{kind}-{now_ns()}"
            if cfg.dry_run and business:
                # 纯观察：业务动作一律拒绝（不碰手机 UI），生命周期动作（唤醒/启动）仍允许，
                # 因为不启动 app 就观察不到任何页面。
                stats.setdefault("dry_rejected", []).append(kind)
                t = max(1, now_ns())
                return ActionReceipt(action_id, ExecutionStatus.REJECTED, t, t,
                                     error_code="dry_run")
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
                                channels=(CoordinateSource.TESSERACT_SPARSE,
                                          CoordinateSource.TESSERACT_PAGE),
                                xml_policy=XmlPolicy.SKIP)
            stats["observe_calls"] += 1
            text = " ".join(ln.normalized_text
                            for ln in parse_tsv("\n".join(obs.ocr_texts.values())))
            fs = device.focus()
            return PageView(fs.focused_package, fs.focused_activity, text)

        runner = StageRunner(read_page, act, policy)

        def entry_anchor_candidates():
            """首页「百亿补贴」入口的**锚点推算**候选点（11-13 加固）。

            背景：「百亿补贴」是艺术字图标，psm6 读成乱码、psm11 偶发（同一张图
            一次 conf 81、另两次 'SEAM' conf 38）→ 不能靠 OCR 认它。
            但同页图标行文字「限时秒杀/充值中心/免费领礼物/多多果园」**稳定可读**
            （11-13 实测 conf 85~97），且百亿补贴卡片恒在其下方同列。

            做法：认到锚点文字 → 按 (dx,dy) 偏移推算候选点 → 逐个试点，
            由落地校验（认到「抽福袋/搜低价/精选+奢品馆」）裁决；
            **认不到锚点就返回空**（绝不盲点）。
            """
            from pddcheck.domain import CoordinateSource
            from pddcheck.perception.anchor import anchor_candidates, words_from_tsv
            from pddcheck.perception import observe_frame
            try:
                src = DeviceVisionSource(device, engine, pill_box=cfg.pill_box,
                                         pill_div=cfg.pill_div, pill_mode=cfg.pill_mode)
                obs = observe_frame(src, frame_id=f"{cfg.run_id}-a", capture_id="anchor",
                                    state_epoch=getattr(device, "state_epoch", 0),
                                    tap_width=getattr(device, "tap_width", 720),
                                    tap_height=getattr(device, "tap_height", 1280),
                                    channels=(CoordinateSource.TESSERACT_SPARSE,
                                              CoordinateSource.TESSERACT_PAGE),
                                    xml_policy=XmlPolicy.SKIP)
                stats["observe_calls"] += 1
                words = words_from_tsv(list(obs.ocr_texts.values()), min_conf=40.0)
                cands = anchor_candidates(
                    words,
                    anchors=cfg.entry_anchor_labels,
                    offsets=cfg.entry_anchor_offsets,
                    scale_w=int(getattr(device, "tap_width", 0) or 720),
                    scale_h=int(getattr(device, "tap_height", 0) or 1280))
                return [(c.x, c.y) for c in cands]
            except Exception as exc:
                stats.setdefault("anchor_errors", []).append(str(exc))
                return []

        def bag_pill_candidates():
            """频道页「抽福袋」裁片候选（真机实测只有 pill color×2 psm7 认得出）。"""
            if cfg.bag_pill is None:
                return ()
            from pddcheck.domain import CoordinateSource, ReadStatus
            from pddcheck.perception import ocr_pass_candidates, parse_tsv
            from pddcheck.perception.ocr_pass import OcrPassInput
            from pddcheck.vision.preprocess import pill_crop_box, preprocess_pill
            import io as _io
            try:
                from PIL import Image
                png = device.screenshot_bytes()
                im = Image.open(_io.BytesIO(png))
                box_spec, mode = cfg.bag_pill
                box = pill_crop_box(box_spec, im.width, im.height)
                g = preprocess_pill(im, box, div=cfg.pill_div, th=cfg.pill_th, mode=mode)
                buf = _io.BytesIO()
                try:
                    g.save(buf, format="PNG")
                except TypeError:
                    g.save(buf)
                tmp = _write_tmp_png(buf.getvalue())
                try:
                    res = engine.recognize(str(tmp), 7)
                finally:
                    tmp.unlink(missing_ok=True)
                if res.status is not ReadStatus.OK:
                    return ()
                sx = float(f"{720 / im.width / cfg.pill_div:.5f}")
                sy = float(f"{1280 / im.height / cfg.pill_div:.5f}")
                ox = float(f"{box[0] / im.width * 720:.1f}")
                oy = float(f"{box[1] / im.height * 1280:.1f}")
                return ocr_pass_candidates(
                    f"{cfg.run_id}-p", "stage", 1,
                    OcrPassInput(source=CoordinateSource.PILL, tsv_text=res.tsv_text,
                                 scale_x=sx, scale_y=sy, offset_x=ox, offset_y=oy),
                    "bag", cfg.specs["bag"].labels,
                    min_overlap=cfg.specs["bag"].min_overlap, min_conf=40)
            except Exception:
                return ()

        try:
            if cfg.dry_run:
                # 纯观察：只做到「把手机带到 PDD + 认出当前页 + 记录本来会点哪里」，
                # 不做任何业务动作（没有跳转就没法继续往下认，硬试只会得到误报 rc4/5）。
                runner.ensure_ready()
                stats["stages"].append("ready:ok")
                from pddcheck.perception.pagekind import classify_page
                v = read_page()
                kind = classify_page(v.ocr_text)
                stats["stages"].append(f"page:{kind.value}")
                stats["dry_intent"] = {
                    "subsidy": list(cfg.specs["subsidy"].coord)
                    if cfg.specs.get("subsidy") and cfg.specs["subsidy"].coord else None,
                    "bag_pill": list(cfg.bag_pill[0]) if cfg.bag_pill else None,
                }
                stats["stages"].append("dry:stop")   # 刻意停在这里，不点任何业务坐标
            else:
                runner.ensure_ready()
                stats["stages"].append("ready:ok")
                # 弹窗清除（用户 11-08 现场口径：屏幕中间「邀请/抽」推广弹窗挡页面）
                popup_spec = cfg.specs.get("popup")
                n_pop = runner.dismiss_popup(popup_spec)
                if n_pop:
                    stats["stages"].append(f"popup:closed{n_pop}")
                runner.enter_subsidy(cfg.specs["subsidy"], scroll_to_top=runner.scroll_to_top,
                                     anchor_points=entry_anchor_candidates)
                stats["stages"].append("entry:ok")
                runner.open_bag(cfg.specs["bag"], extra_candidates=bag_pill_candidates)
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
                   stage_failure_why=stats.get("stage_failure"),
                   dry_run=cfg.dry_run,
                   browse_after_light=cfg.browse_after_light,
                   execute_terminal_effects=cfg.execute_terminal_effects,
                   verify_ladder=cfg.verify_ladder)
    outcome = run_once(deps)
    stats["observe_calls"] = screen.observe_calls
    return outcome, stats
