"""真机流程演练（dry-run/实跑共用）：就绪→入口→福袋→点亮，逐段记录「认到了什么、想点哪」。

动作策略：
  --dry-run（默认）：识别与决策全做，动作全部记录但**不执行**（绝不碰手机 UI）；
  --execute：执行真实动作（受 AdbDevice 的前台校验护栏）。
每一步落 JSONL 到 --log，供事后复盘。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pddcheck.device.adb import AdbDevice
from pddcheck.domain import CoordinateSource, ExecutionStatus
from pddcheck.perception import TargetLocateSpec
from pddcheck.perception.facts import facts_from_text
from pddcheck.perception.observe import XmlPolicy
from pddcheck.vision.engine import TesseractEngine
from pddcheck.vision.source import DeviceVisionSource
from pddcheck.workflow.stages import PageView, StageFailure, StagePolicy, StageRunner

PKG = "com.xunmeng.pinduoduo"
HOME_ACT = "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
# 真机实测（t18a-calibration-findings）：频道页「抽福袋」只有 pill color×2 psm7 认得出
BAG_PILL = (0.472, 0.375, 0.75, 0.4375)

SPECS = {
    "subsidy": TargetLocateSpec(key="subsidy", labels=("百亿补贴", "搜索补贴", "签到"),
                                min_overlap=3, coord=(0.125, 0.46875)),
    "bag": TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3),
    "light": TargetLocateSpec(key="light", labels=("立即点亮", "今日已点亮"), min_overlap=4),
    "done": TargetLocateSpec(key="done", labels=("今日已点亮", "已使用"), min_overlap=3),
}


class Recorder:
    def __init__(self, log_path: Path, execute: bool) -> None:
        self.log_path = log_path
        self.execute = execute
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.log_path, "a", encoding="utf-8")
        self.n = 0

    def write(self, **row) -> None:
        self.n += 1
        self.fh.write(json.dumps({"seq": self.n, "t": time.strftime("%H:%M:%S"), **row},
                                 ensure_ascii=False) + "\n")
        self.fh.flush()

    def close(self) -> None:
        self.fh.close()


class ActionBridge:
    """把 StageRunner 的 act() 落到设备或只记录（dry-run）。

    允许的动作集合可单独放开：--execute-lifecycle 只放行 wake/dismiss_keyguard/start
    （不改 UI 状态，只把 app 拉到前台），业务 tap/back 仍然只记录——用于「真启动、
    假点击」的半实跑。
    """

    def __init__(self, device, rec: Recorder, execute: bool,
                 lifecycle_only: bool = False, allow_entry_coord_tap: bool = False) -> None:
        self.device = device
        self.rec = rec
        self.execute = execute
        self.lifecycle_only = lifecycle_only
        self._allow_entry_coord_tap = allow_entry_coord_tap
        self._LIFECYCLE = {"wake", "dismiss_keyguard", "start"}

    def _allowed(self, kind: str) -> bool:
        if not self.execute:
            return False
        # entry-tap 开关优先级更高：它要放行 tap/back，lifecycle_only 只放行生命周期。
        if self._allow_entry_coord_tap:
            return kind in ("tap", "back") or kind in self._LIFECYCLE
        if self.lifecycle_only:
            return kind in self._LIFECYCLE
        return False

    def __call__(self, kind, point):
        allowed = self._allowed(kind)
        self.rec.write(kind="action", action=kind, point=list(point) if point else None,
                       executed=allowed)
        if not allowed:
            return None
        from pddcheck.domain import ActionIntent, ActionKind, WindowKind
        mapping = {"tap": ActionKind.TAP, "back": ActionKind.BACK, "start": ActionKind.START,
                   "wake": ActionKind.WAKE, "dismiss_keyguard": ActionKind.DISMISS_KEYGUARD,
                   "swipe": ActionKind.SWIPE}
        kind_enum = mapping[kind]
        business = kind_enum in (ActionKind.TAP, ActionKind.BACK, ActionKind.SWIPE)
        intent = ActionIntent(
            action_id=f"rehearsal-{self.rec.n}-{kind}",
            run_id="rehearsal", kind=kind_enum,
            source_capture_id="cap", state_epoch=getattr(self.device, "state_epoch", 0),
            geometry_revision=0, deadline_ns=time.monotonic_ns() + 30_000_000_000,
            reason=f"rehearsal {kind}",
            source_candidate_id=("cand-rehearsal" if business else None),
            target_key=("rehearsal" if business else None),
            expected_package=(PKG if business else None),
            required_window_kind=(WindowKind.APP if business else None),
            allow_coord=bool(business and kind == "tap"))
        receipt = self.device.execute(intent, point)
        self.rec.write(kind="receipt", action=kind, status=receipt.status.value,
                       error=receipt.error_code)
        return receipt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--execute", action="store_true", help="真执行（默认 dry-run）")
    ap.add_argument("--execute-lifecycle", action="store_true",
                    help="只放行 wake/解锁/start（不点任何业务坐标）")
    ap.add_argument("--execute-entry-tap", action="store_true",
                    help="放行入口坐标那一枪（艺术字入口，OCR 认不出；前台护栏仍然生效）")
    ap.add_argument("--skip-ready", action="store_true", help="跳过就绪段（手机已在 pdd）")
    a = ap.parse_args(argv)
    rec = Recorder(Path(a.log), a.execute)
    # 真实 launcher activity（实机 resolve-activity 得到；显式启动，禁止 monkey 兜底）
    dev = AdbDevice(a.serial, home_activity="com.xunmeng.pinduoduo/.ui.activity.MainFrameActivity")
    dev.connect()
    rec.write(kind="connect", serial=a.serial)

    engine = TesseractEngine()
    frames = {"n": 0}

    def read_page() -> PageView:
        t0 = time.monotonic()
        png = dev.screenshot_bytes()
        from pddcheck.perception import locate_all, observe_frame, parse_tsv
        from pddcheck.domain import ReadStatus
        from pddcheck.vision.preprocess import band_crop_box, preprocess_band
        texts = []
        for psm in (6, 11):                      # 多通道：psm6 切行、psm11 保行
            src = DeviceVisionSource(dev, engine, psm=psm, screenshot=lambda: png)
            obs = observe_frame(src, frame_id=f"f{frames['n']}", capture_id="cap",
                                state_epoch=dev.state_epoch, tap_width=720, tap_height=1280,
                                channels=(CoordinateSource.TESSERACT_PAGE,),
                                xml_policy=XmlPolicy.SKIP)
            for t in obs.ocr_texts.values():
                texts.append(t)
        # band 通道：裁片 ×3 + autocontrast（旧脚本认小字的关键，10-10 矩阵证明整页不够）
        try:
            import io
            from PIL import Image
            im = Image.open(io.BytesIO(png))
            box = band_crop_box((0.0, 0.35, 1.0, 0.85), im.width, im.height)
            crop = preprocess_band(im, box, scale=3, cutoff=1)
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            tmp = f"/tmp/pdd-band-{frames['n']}.png"
            open(tmp, "wb").write(buf.getvalue())
            res = engine.recognize(tmp, 7)
            if res.status is ReadStatus.OK:
                texts.append(res.tsv_text)
            rec.write(kind="band", box=list(box), chars=len(res.tsv_text or ""))
        except Exception as exc:
            rec.write(kind="band_error", error=f"{type(exc).__name__}: {exc}")
        # pill 通道：真机实测频道页「抽福袋」只有这个配方认得出（color ×2 psm7）
        try:
            import io
            from PIL import Image
            from pddcheck.vision.preprocess import pill_crop_box, preprocess_pill
            im2 = Image.open(io.BytesIO(png))
            pbox = pill_crop_box(BAG_PILL, im2.width, im2.height)
            pcrop = preprocess_pill(im2, pbox, div=2, th=120, mode="color")
            pbuf = io.BytesIO()
            try:
                pcrop.save(pbuf, format="PNG")
            except TypeError:
                pcrop.save(pbuf)
            ptmp = f"/tmp/pdd-pill-{frames['n']}.png"
            open(ptmp, "wb").write(pbuf.getvalue())
            pres = engine.recognize(ptmp, 7)
            if pres.status is ReadStatus.OK:
                # 几何：scale=TAP/整图/2（5dp）、offset=裁片原点回推（1dp）
                sx = float(f"{720/im2.width/2:.5f}")
                sy = float(f"{1280/im2.height/2:.5f}")
                ox = float(f"{pbox[0]/im2.width*720:.1f}")
                oy = float(f"{pbox[1]/im2.height*1280:.1f}")
                pill_text = pres.tsv_text
                from pddcheck.perception import ocr_pass_candidates
                from pddcheck.perception.ocr_pass import OcrPassInput
                pc = ocr_pass_candidates("f", "cap", 1,
                                         OcrPassInput(source=CoordinateSource.PILL,
                                                      tsv_text=pill_text,
                                                      scale_x=sx, scale_y=sy,
                                                      offset_x=ox, offset_y=oy),
                                         "bag", ("抽福袋",), min_overlap=3, min_conf=40)
                rec.write(kind="pill", box=list(pbox), geom=[sx, sy, ox, oy],
                          candidates=[(list(c.tap_point), c.overlap) for c in pc])
                last_pill_cands["c"] = pc
            else:
                last_pill_cands["c"] = ()
                rec.write(kind="pill", status=str(pres.status))
        except Exception as exc:
            last_pill_cands["c"] = ()
            rec.write(kind="pill_error", error=f"{type(exc).__name__}: {exc}")

        frames["n"] += 1
        raw = "\n".join(texts)
        lines = parse_tsv(raw)
        readable = " ".join(ln.normalized_text for ln in lines)
        focus = dev.focus()
        rec.write(kind="page", n=frames["n"], ms=round((time.monotonic() - t0) * 1000),
                  pkg=focus.focused_package, act=focus.focused_activity,
                  chars=len(readable), text=readable[:200])
        return PageView(focus.focused_package, focus.focused_activity, readable)

    def scroll_to_top(self, swipes: int = 3):
        """滑回页面顶部（旧脚本 TOP_RETRY 的做法），再认一轮入口。"""
        runner.scroll_to_top(swipes)

    # 裁片通道候选供给器：StageRunner 用它补整页认不到的「抽福袋」
    last_pill_cands = {"c": ()}

    def pill_candidates():
        return last_pill_cands["c"]
    bridge = ActionBridge(dev, rec, a.execute or a.execute_lifecycle or a.execute_entry_tap,
                          lifecycle_only=a.execute_lifecycle,
                          allow_entry_coord_tap=a.execute_entry_tap)
    policy = StagePolicy(pkg=PKG, home_activity=HOME_ACT, entry_retry=2, prove_max=3)
    runner = StageRunner(read_page, bridge, policy)
    stages = []
    try:
        if not a.skip_ready:
            runner.ensure_ready()
            stages.append("ready:ok")
        else:
            # --skip-ready 也要回到确定起点（首页），否则页面残留会让后续判定漂移
            runner.ensure_ready(back_to_home=3)
            stages.append("ready:forced")
        runner.enter_subsidy(SPECS["subsidy"], scroll_to_top=runner.scroll_to_top)
        stages.append("entry:ok")
        runner.open_bag(SPECS["bag"], extra_candidates=pill_candidates)
        stages.append("bag:ok")
        # 点亮页事实
        v = read_page()
        f = facts_from_text(v.ocr_text)
        rec.write(kind="light_facts", progress=f.progress_count, done=f.done_text,
                  exchange=f.exchange_text, pend=f.pend_text)
        stages.append("facts:read")
    except StageFailure as exc:
        rec.write(kind="stage_failed", rc=exc.rc, why=exc.why)
        stages.append(f"failed:rc{exc.rc}")
    finally:
        rec.write(kind="stages", stages=stages, executed=(a.execute or a.execute_lifecycle))
        rec.close()
    print(json.dumps({"stages": stages, "pages": frames["n"], "log": str(Path(a.log))},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
