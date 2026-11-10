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


def _cmd_run(args) -> CliResult:
    """run：真实适配器装配（AdbDevice + TesseractEngine）→ bootstrap 端到端。"""
    from pathlib import Path
    from pddcheck.cli.bootstrap import PipelineConfig, build_and_run
    from pddcheck.device.adb import AdbDevice, AdbError
    from pddcheck.exits import ExitCode
    from pddcheck.notify import NotificationSender, read_endpoint_file
    from pddcheck.perception import TargetLocateSpec
    from pddcheck.storage import DailyStore, Journal, LockBusy, acquire_run_lease
    from pddcheck.vision.engine import TesseractEngine
    import os

    serial = args.device or os.environ.get("PDDCHECK_DEVICE", "")
    if not serial:
        return CliResult(ExitCode.NO_ADB,
                         stderr="run 需要 --device <serial> 或 PDDCHECK_DEVICE（禁止自动选设备）\n")
    home = Path(os.environ.get("HOME", "."))
    state = Path(os.environ.get("PDDCHECK_STATE", home / ".local" / "share" / "pddcheck"))
    ev = Path(os.environ.get("PDDCHECK_EVIDENCE", home / "pddcheck-runs"))
    date = __import__("datetime").date.today().isoformat()

    specs = {
        "subsidy": TargetLocateSpec(key="subsidy", labels=("百亿补贴", "搜索补贴"), min_overlap=3,
                                    coord=(0.125, 0.46875)),
        "bag": TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3,
                                coord=(0.13889, 0.69922)),
        "light": TargetLocateSpec(key="light", labels=("立即点亮",), min_overlap=4),
        # 弹窗关闭词（旧脚本 POPUP 同款；profile [targets.popup] 同口径）
        "popup": TargetLocateSpec(key="popup", labels=("关闭", "跳过广告", "暂不", "以后再说"),
                                  min_overlap=2),
        # 奖励浮层主按钮「开心收下」（G3 迁移；profile [targets.take] 同口径）。
        # 整页读不到它，靠 coord 兜底 / 裁片档；只有奖励浮层证明分支会用这颗点。
        "take": TargetLocateSpec(key="take", labels=("开心收下",), min_overlap=3,
                                 coord=(0.49861, 0.58750)),
    }
    # --stages：先走 就绪→入口→福袋 流程段（真机验证见 t18a-calibration-findings.md）。
    run_stages = bool(getattr(args, "stages", False))
    # light/done 右上按钮裁片（真机验证：pill inv×2 psm7 读「立即点亮/今日已点亮」conf 96）
    light_pill = ((0.597, 0.184, 1.0, 0.270), "inv")
    # bag 裁片标定：优先读 profile 的 pill_channel（ADR-003；用户批准后写入即生效），
    # 读不到再用真机验证过的 fallback（t18a-calibration-findings §2，(435,524)）。
    bag_pill = None
    if run_stages:
        try:
            from pddcheck.config.profile import load_profile
            prof = load_profile(Path(__file__).resolve().parents[2] / "profiles"
                                / "pdd" / "v1" / "profile.toml")
            pc = prof.target("bag").pill_channel
        except Exception:
            pc = None
        bag_pill = (pc, "color") if pc is not None else ((0.472, 0.375, 0.75, 0.4375), "color")
    # 真机路径：点亮后浏览任务段（滑动 10s）——47 案基线不含此段，CLI 显式开
    browse_after_light = not bool(getattr(args, "dry_run", False))
    # 真机路径：终态效果（I06 最终 20 次下滑 + close_policy 下发 + last_activity）
    # ——迁移审计 G4/G8；dry-run 仍不执行任何业务/收尾动作
    execute_terminal_effects = not bool(getattr(args, "dry_run", False))
    # 真机路径：verify 四阶段阶梯（browse→BACK→reconcile / 清浮层 / 收奖）
    # ——迁移审计 G1/G2/G3/G5；dry-run 不跑
    verify_ladder = not bool(getattr(args, "dry_run", False))
    cfg = PipelineConfig(
        business_date=date, run_id=f"run-{date}",
        evidence_dir=str(ev / date),
        endpoint=(None if os.environ.get("PDDCHECK_NO_PUSH") == "1"
                  else read_endpoint_file(home / "Desktop" / "pdd-push.url")),
        force=bool(getattr(args, "force", False)), specs=specs,
        run_stages=run_stages,
        dry_run=bool(getattr(args, "dry_run", False)),
        bag_pill=bag_pill,
        light_pill=light_pill,
        browse_after_light=browse_after_light,
        execute_terminal_effects=execute_terminal_effects,
        verify_ladder=verify_ladder)
    # 显式 HOME_ACT（真机 resolve-activity 实测；护栏要求，禁止 monkey 兜底）
    dev = AdbDevice(serial, home_activity=cfg.home_activity)
    try:
        dev.connect()
    except AdbError as exc:
        return CliResult(ExitCode.NO_ADB if exc.code in ("adb_failed", "serial_required") else
                         ExitCode.DEVICE_GONE, stderr=f"连接失败：{exc}\n")
    store = DailyStore(ev, home / "Desktop" / "pdd-pause")
    lease = None
    try:
        lease = acquire_run_lease(state / "run.lock", args.device)
    except LockBusy:
        return CliResult(ExitCode.LOCK_BUSY, stderr="另一个实例持锁\n")
    try:
        outcome, stats = build_and_run(
            device=dev, engine=TesseractEngine(), store=store,
            notifier=NotificationSender(), journal=Journal(state / "journal" / "actions.jsonl"),
            cfg=cfg, now_ns=lambda: __import__("time").monotonic_ns(),
            lease_factory=None)
        line = (f"run {date}: exit={int(outcome.exit_code)} lit={outcome.lit} rc={outcome.rc} "
                f"marker={outcome.marker_written} ledger={outcome.ledger_written} "
                f"delivered={outcome.delivered} observes={stats['observe_calls']}\n")
        # 流程段失败原因必须可见（生产 11-09 教训：rc7 的 why 只进 notes 被吞，
        # 查因要靠重跑诊断）。stages 列表 + 失败 why 全部打出来。
        if stats.get("stages"):
            line += f"stages={stats['stages']}\n"
        if stats.get("stage_failure"):
            line += f"stage_failure={stats['stage_failure']}\n"
        return CliResult(outcome.exit_code, stdout=line)
    finally:
        if lease is not None:
            lease.release()


def _cmd_version(_args) -> CliResult:
    import pddcheck.domain.version as v
    return CliResult(ExitCode.OK, f"pddcheck schema_version={v.SCHEMA_VERSION}\n")


def _cmd_check_config(args) -> CliResult:
    try:
        profile = load_profile(Path(args.profile) if args.profile else None)
    except ConfigError as exc:
        return CliResult(ExitCode.PRECHECK_FAILED, stderr=f"配置非法：{exc}\n")
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
_DEVICE_ONLY = frozenset({"probe", "find", "shot"})


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
        sp.add_argument("--stages", action="store_true",
                        help="先走 就绪→入口→福袋 流程段（默认只做点亮段）")
        sp.add_argument("--dry-run", action="store_true",
                        help="纯观察：识别与决策照做，不执行业务动作、不写标记/账本、不推送（只留证据）")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "run":
        result = _cmd_run(args)
    elif args.cmd in _DEVICE_ONLY:
        # 其余设备命令暂未接（probe/find/shot）
        print(f"{args.cmd}: 尚未接通——离线命令可用：version/check-config/doctor/replay/run",
              file=sys.stderr)
        return int(ExitCode.NO_ADB)
    else:
        result = _COMMANDS[args.cmd](args)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return int(result.code)


def _console() -> None:
    """console_scripts 入口：把 main 的返回码转成进程退出码。"""
    raise SystemExit(main())


if __name__ == "__main__":
    _console()
