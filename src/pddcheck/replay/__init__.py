"""replay：回放与静态报告（T13）。完全离线——无 ADB、无 endpoint、无 socket。

- 三种模式：exact（不重跑 OCR，复用记录）、reprocess（重识别并标注原/新结果）、
  trace（按序驱动同一状态机核对记录）；
- trace.exact 走 workflow 判定核，保证与线上同一套语义；
- 缺 OCR/关键帧 → INCOMPLETE 并给出统计，绝不伪造为成功。
"""

from pddcheck.replay.trace import (
    ReplayMode,
    ReplayResult,
    ReplayStatus,
    RunTrace,
    diff_runs,
    exact_replay,
    load_run,
    trace_replay,
)
from pddcheck.replay.report import render_report

__all__ = [
    "ReplayMode",
    "ReplayResult",
    "ReplayStatus",
    "RunTrace",
    "load_run",
    "exact_replay",
    "trace_replay",
    "diff_runs",
    "render_report",
]
