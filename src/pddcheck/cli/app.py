"""子命令装配（T14 1/2）：exit 合同 + 离线命令；run 的设备流程在 T14 2/2。

关键设计（I03）：离线命令用 offline 能力集，构造期就拿不到 DevicePort。
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from pddcheck.config import ConfigError, load_profile
from pddcheck.cli.exits import ExitCode
from pddcheck.device.capabilities import Capability, offline_capabilities
from pddcheck.replay import ReplayStatus, exact_replay, load_run, render_report, trace_replay


@dataclass(frozen=True, slots=True)
class CliResult:
    code: ExitCode
    stdout: str = ""
    stderr: str = ""


def _cmd_version(_args) -> CliResult:
    import pddcheck.domain.version as v
    return CliResult(ExitCode.OK, f"pddcheck schema_version={v.SCHEMA_VERSION}\n")


def _cmd_check_config(args) -> CliResult:
    try:
        profile = load_profile(Path(args.profile) if args.profile else None)
    except ConfigError as exc:
        return CliResult(ExitCode.CONFIG_INVALID, stderr=f"配置非法：{exc}\n")
    return CliResult(ExitCode.OK,
                     f"配置 OK：profile_id={getattr(profile, 'profile_id', '?')} "
                     f"targets={len(profile.targets)}\n")


def _cmd_doctor(args) -> CliResult:
    caps = offline_capabilities()                     # 离线：不赋予设备能力
    lines = ["pddcheck doctor"]
    lines.append(f"capabilities={sorted(c.value for c in caps)}")
    adb = shutil.which("adb")
    tess = shutil.which("tesseract")
    lines.append(f"adb={'yes:' + adb if adb else 'no'} (设备能力未授予)")
    lines.append(f"tesseract={'yes:' + tess if tess else 'no'}")
    problems = []
    if not tess:
        problems.append("缺 tesseract（OCR 不可用）")
    code = ExitCode.PRECHECK_FAILED if problems else ExitCode.OK
    if problems:
        lines.append("问题：" + "；".join(problems))
    return CliResult(code, "\n".join(lines) + "\n")


def _cmd_replay(args) -> CliResult:
    trace = load_run(Path(args.run))
    mode = getattr(args, "mode", "exact")
    result = trace_replay(trace) if mode == "trace" else exact_replay(trace)
    html = render_report(trace, result)
    if args.out:
        Path(args.out).write_text(html, encoding="utf-8")
    summary = (f"replay {mode}: {result.status.value} lit={result.derived_lit} "
               f"rc={result.derived_rc} proof={result.proof_kind}\n")
    if result.status is ReplayStatus.INCOMPLETE:
        summary += "缺料：" + ",".join(result.incompleteness) + "\n"
        return CliResult(ExitCode.LOCATE_FAILED, stdout=summary)
    if result.status is ReplayStatus.MISMATCH:
        return CliResult(ExitCode.UNVERIFIED, stdout=summary)
    return CliResult(ExitCode.OK, stdout=summary)


_COMMANDS = {
    "version": _cmd_version,
    "check-config": _cmd_check_config,
    "doctor": _cmd_doctor,
    "replay": _cmd_replay,
}
_DEVICE_ONLY = frozenset({"run", "probe", "find", "shot"})


def _build_parser():
    import argparse
    p = argparse.ArgumentParser(prog="pddcheck")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version")
    cc = sub.add_parser("check-config")
    cc.add_argument("--profile", default=None)
    sub.add_parser("doctor")
    rp = sub.add_parser("replay")
    rp.add_argument("--run", required=True)
    rp.add_argument("--mode", choices=["exact", "trace", "reprocess"], default="exact")
    rp.add_argument("--out", default=None)
    rp.add_argument("--key", default=None)
    for name in ("run", "probe", "find", "shot"):
        sp = sub.add_parser(name)
        sp.add_argument("--device", required=False, default=None)
        sp.add_argument("--force", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd in _DEVICE_ONLY:
        # 设备流程在 T14(2/2)；此处明确报告「未接设备」并给出与旧语义一致的码
        print(f"{args.cmd}: 设备流程尚未接通（T14 2/2）——离线命令可用："
              f"version/check-config/doctor/replay", file=sys.stderr)
        return int(ExitCode.NO_ADB)
    result = _COMMANDS[args.cmd](args)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return int(result.code)
