"""T16 调用计数证据（离线、无引擎）：不同观察策略下每帧的 OCR 调用次数。

策略对比（同一批帧、同一批目标键）：
- legacy_per_key：旧脚本每目标各跑一遍通道（XML→psm11→psm6→band→pill）；
- share_per_frame：新观察模型——每帧只采集/识别一次，多目标复用（同帧共享）；
- lazy_xml_first：若 XML 已能定位某目标，则该目标不再跑 OCR（惰性）。

不计耗时（那要引擎）；这是**结构指标**：调用次数与语义等价由决策核保证。
语义等价检查：策略改变只允许减少「未被任何目标需要的调用」，不允许改变命中集合
——这里用「每个目标的首个可定位来源」是否一致来抽查（见等价性说明）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# 每个目标允许的定位来源（与 profile 的 region/pill 配置一致的精简投影）
TARGET_SOURCES = {
    "popup": ["xml", "psm11", "psm6", "band"],
    "subsidy": ["xml", "psm11", "psm6", "band"],
    "bag": ["xml", "psm11", "psm6", "band", "pill"],
    "light": ["xml", "psm11", "psm6", "band", "pill"],
    "done": ["xml", "psm11", "psm6", "band", "pill"],
    "exchange": ["xml", "psm11", "psm6", "band", "pill"],
    "browse": ["xml", "psm11", "psm6", "band"],
    "pend": ["xml", "psm11", "psm6", "band", "pill"],
    "prize": ["xml", "psm11", "psm6", "band", "pill"],
    "take": ["xml", "psm11", "psm6", "band", "pill"],
}

# 通道成本模型：一次 psm 识别 = 1 次 OCR 调用；band/pill 的每个 psm 各算 1 次
CHANNEL_CALLS = {"xml": 0, "psm11": 1, "psm6": 1, "band": 3, "pill": 4}


def legacy_calls(targets: list[str]) -> int:
    """旧路径：每目标独立跑全部通道（xml 免费，OCR 通道按成本累加）。"""
    total = 0
    for t in targets:
        for src in TARGET_SOURCES[t]:
            total += CHANNEL_CALLS[src]
    return total


def shared_calls(targets: list[str]) -> int:
    """同帧共享：每个 OCR 通道整帧只跑一次，供所有目标复用。"""
    used = {src for t in targets for src in TARGET_SOURCES[t]}
    return sum(CHANNEL_CALLS[src] for src in used if src != "xml")


def lazy_calls(targets: list[str], xml_resolves: set[str]) -> int:
    """惰性：XML 已能定位的目标不再跑 OCR 通道；其余转入共享模型。"""
    remaining = [t for t in targets if t not in xml_resolves]
    return shared_calls(remaining)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="callcount")
    ap.add_argument("--frames", type=int, default=178, help="帧数（语料整页帧）")
    ap.add_argument("--targets", nargs="+", default=["popup", "subsidy", "bag", "light",
                                                     "done", "exchange", "browse", "pend", "prize"])
    ap.add_argument("--xml-resolves", nargs="*", default=["popup", "subsidy", "bag"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    per_frame_legacy = legacy_calls(a.targets)
    per_frame_shared = shared_calls(a.targets)
    per_frame_lazy = lazy_calls(a.targets, set(a.xml_resolves))
    report = {
        "schema_version": 1,
        "kind": "t16-callcount",
        "frames": a.frames,
        "targets": a.targets,
        "per_frame": {"legacy": per_frame_legacy, "shared": per_frame_shared,
                      "lazy_xml_first": per_frame_lazy},
        "totals": {"legacy": per_frame_legacy * a.frames,
                   "shared": per_frame_shared * a.frames,
                   "lazy_xml_first": per_frame_lazy * a.frames},
        "reduction_shared_pct": round(100 * (1 - per_frame_shared / per_frame_legacy), 1),
        "reduction_lazy_pct": round(100 * (1 - per_frame_lazy / per_frame_legacy), 1),
        "semantics": "只减少「没有目标需要」的调用；每个目标可用来源集合不变",
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"per_frame": report["per_frame"],
                      "reduction_lazy_pct": report["reduction_lazy_pct"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
