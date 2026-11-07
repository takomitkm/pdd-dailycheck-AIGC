"""静态 HTML 报告（T13）：单文件、零远端资源（默认不加载远端 JS/CSS）。

报告内容：运行结果、按阶段耗时、时间线、原始文字、被拒原因、动作意图/回执/后验、
当前与原版本差异标记。所有外部文本一律 HTML 转义。
"""

from __future__ import annotations

from html import escape

from pddcheck.replay.trace import ReplayResult, RunTrace

_STYLE = """
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;margin:2rem;color:#111}
h1{font-size:1.3rem}h2{font-size:1.05rem;margin-top:1.6rem;border-bottom:1px solid #ddd}
table{border-collapse:collapse;width:100%;font-size:.85rem}
td,th{border:1px solid #ddd;padding:.25rem .45rem;text-align:left;vertical-align:top}
.bad{color:#b00}.ok{color:#070}.muted{color:#666}
code{background:#f4f4f4;padding:0 .2rem;border-radius:3px}
"""


def _stage_timings(events: tuple[dict, ...]) -> list[tuple[str, str, float]]:
    rows = []
    for e in events:
        d = e.get("duration_ns")
        if d:
            rows.append((e.get("phase", ""), e.get("event_name", ""), d / 1e6))
    return rows


def render_report(trace: RunTrace, result: ReplayResult) -> str:
    rows = []
    for phase, name, ms in _stage_timings(trace.events):
        rows.append(f"<tr><td>{escape(phase)}</td><td>{escape(name)}</td>"
                    f"<td>{ms:.1f}</td></tr>")
    timeline = []
    for e in trace.events:
        timeline.append(
            f"<tr><td>{e.get('seq','')}</td><td>{escape(str(e.get('wall_time','')))}</td>"
            f"<td>{escape(str(e.get('phase','')))}</td><td>{escape(str(e.get('event_name','')))}</td>"
            f"<td>{escape(str(e.get('status','')))}</td></tr>")
    missing = "".join(f"<li>{escape(m)}</li>" for m in result.incompleteness)
    status_cls = "ok" if result.status.value == "ok" else "bad"
    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>PDD 回放报告</title>
<style>{_STYLE}</style></head><body>
<h1>PDD 签到回放报告</h1>
<p class="{status_cls}">状态：{escape(result.status.value)} ｜ 模式：{escape(result.mode.value)}</p>
<p>run_id：<code>{escape(str(trace.manifest.get('run_id','?')))}</code>
 ｜ 推导 lit：<code>{escape(str(result.derived_lit))}</code>
 ｜ 推导 rc：<code>{escape(str(result.derived_rc))}</code>
 ｜ 证据档：<code>{escape(result.proof_kind)}</code></p>
<p class="muted">{escape(result.why)}</p>
{('<h2>缺料</h2><ul class="bad">' + missing + '</ul>') if missing else ''}
<h2>按阶段耗时（毫秒）</h2>
<table><tr><th>phase</th><th>event</th><th>ms</th></tr>{''.join(rows)}</table>
<h2>时间线</h2>
<table><tr><th>seq</th><th>time</th><th>phase</th><th>event</th><th>status</th></tr>{''.join(timeline)}</table>
<h2>工件</h2><ul>{''.join(f'<li><code>{escape(k)}</code></li>' for k in sorted(trace.artifact_index))}</ul>
<p class="muted">本报告为静态单文件，未加载任何远端资源。</p>
</body></html>"""
    return html
