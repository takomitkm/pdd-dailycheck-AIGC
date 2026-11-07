"""T16 真机干跑（零副作用）：真实采集+OCR+定位+决策，动作执行器禁用，绝不点击。

在 h61 上运行（有 adb+tesseract）。输出：每一步耗时、定位结果、若执行会做的决策。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from pddcheck.device.adb import AdbDevice
from pddcheck.domain import CoordinateSource, ExecutionStatus
from pddcheck.perception import TargetLocateSpec, locate_all, observe_frame
from pddcheck.perception.facts import facts_from_text
from pddcheck.perception.observe import xml_policy_for
from pddcheck.vision.engine import TesseractEngine
from pddcheck.vision.source import DeviceVisionSource


class DryRunDevice:
    """包住真实设备：观测透传，任何动作一律拒绝（零副作用）。"""

    def __init__(self, inner: AdbDevice) -> None:
        self._inner = inner
        self.state_epoch = inner.state_epoch

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute(self, intent, point=None):
        from pddcheck.domain import ActionReceipt
        now = 0
        return ActionReceipt(intent.action_id, ExecutionStatus.REJECTED, now, now,
                             "dry_run_blocked")


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    serial = argv[0]
    profile_path = argv[1] if len(argv) > 1 else None
    out = Path(argv[2]) if len(argv) > 2 else Path("dryrun.json")
    t = {}
    t0 = time.monotonic()
    dev = AdbDevice(serial)
    dev.connect()
    t["connect_ms"] = round((time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    png = dev.screenshot_bytes()
    t["screencap_ms"] = round((time.monotonic() - t0) * 1000)
    t["png_bytes"] = len(png)

    engine = TesseractEngine()
    # 复用上面已取的这一帧，避免 observe 里再截一次（真机测量证实重复截图 ~0.7s）
    src = DeviceVisionSource(DryRunDevice(dev), engine, psm=6, screenshot=lambda: png)
    specs = {
        "bag": TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3,
                                coord=(0.13889, 0.69922)),
        "light": TargetLocateSpec(key="light", labels=("立即点亮",), min_overlap=4),
        "subsidy": TargetLocateSpec(key="subsidy", labels=("百亿补贴",), min_overlap=3),
        "done": TargetLocateSpec(key="done", labels=("今日已点亮", "已使用"), min_overlap=3),
    }
    t0 = time.monotonic()
    obs = observe_frame(src, frame_id="dry", capture_id="dry", state_epoch=dev.state_epoch,
                        tap_width=720, tap_height=1280,
                        channels=(CoordinateSource.TESSERACT_PAGE,),
                        xml_policy=xml_policy_for("activity"))
    t["observe_ms"] = round((time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    results = locate_all(obs, specs, min_conf=40)
    t["locate_ms"] = round((time.monotonic() - t0) * 1000)

    text = "\n".join(obs.ocr_texts.values())
    facts = facts_from_text(text)
    decision = {
        "done": facts.done_text is not None,
        "exchange": facts.exchange_text is not None,
        "pend": facts.pend_text is not None,
        "progress_count": facts.progress_count,
        "light_tap": (results["light"].winning.tap_point if results.get("light") and results["light"].winning else None),
        "bag_tap": (results["bag"].winning.tap_point if results.get("bag") and results["bag"].winning else None),
    }
    report = {"serial": serial, "timings": t,
              "ocr_chars": len(text), "locate": {k: str(v.status.value) for k, v in results.items()},
              "facts": {"progress_count": facts.progress_count, "done": facts.done_text,
                        "exchange": facts.exchange_text, "pend": facts.pend_text},
              "would_do": decision, "actions_blocked": True}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
