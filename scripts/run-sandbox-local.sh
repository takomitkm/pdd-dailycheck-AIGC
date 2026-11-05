#!/usr/bin/env bash
# 本地直跑桩沙箱（T00 新增）—— 不 SSH、不碰手机、不联网、不读端点文件。
#
# 用法：
#   bash scripts/run-sandbox-local.sh                          # 720x1280 全矩阵（47 例）
#   bash scripts/run-sandbox-local.sh --size 1440x2560         # 换一块屏
#   bash scripts/run-sandbox-local.sh --only happy-ocr         # 只跑一例
#   bash scripts/run-sandbox-local.sh --artifacts DIR          # 产物根目录（默认 reports/t00/<时间戳>）
#   bash scripts/run-sandbox-local.sh --json-out FILE          # 结果 JSON 另存一份
#   bash scripts/run-sandbox-local.sh --self-check             # 不跑沙箱，验分类器逻辑（8 个向量）
#   bash scripts/run-sandbox-local.sh --aggregate DIR --out F  # 把 DIR 下的 result.json 聚合成门禁总表
#   反例（G0a 要求门禁能被这些打红；--expect-fail 指定预期 verdict）：
#   bash scripts/run-sandbox-local.sh --only 不存在的用例 --counterexample bad-only --expect-fail only-unknown
#   bash scripts/run-sandbox-local.sh --timeout 2 --counterexample forced-timeout --expect-fail timeout
#   bash scripts/run-sandbox-local.sh --break-stub adb --counterexample missing-end-marker --expect-fail infra
#   bash scripts/run-sandbox-local.sh --only happy-ocr --unknown-stub-cmd --counterexample unknown-stub-cmd --expect-fail cases-failed
#
# 退出码：0 = 门禁过（或反例如预期失败）；非零 = 门禁红（原因见 JSON 的 verdict）。
# 旧远程 runner（scripts/run-sandbox.sh）保留为显式选项；本地一律走本脚本。
set -u

die() { printf 'RUN-SANDBOX-LOCAL: %s\n' "$*" >&2; exit 9; }
log() { printf '[run-sandbox-local] %s\n' "$*"; }

usage() { sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SIZE=720x1280
ONLY=
TIMEOUT=2400
ARTDIR=
JSON_OUT=
MODE=run
AGG_DIR=
AGG_OUT=
CEX_NAME=
CEX_EXPECT=
BREAK_STUB=
UNKNOWN_STUB=0

while [ $# -gt 0 ]; do
  case $1 in
    --size) SIZE=${2:?}; shift 2 ;;
    --only) ONLY=${2:?}; shift 2 ;;
    --timeout) TIMEOUT=${2:?}; shift 2 ;;
    --artifacts) ARTDIR=${2:?}; shift 2 ;;
    --json-out) JSON_OUT=${2:?}; shift 2 ;;
    --self-check) MODE=selfcheck; shift ;;
    --aggregate) MODE=aggregate; AGG_DIR=${2:?}; shift 2 ;;
    --out) AGG_OUT=${2:?}; shift 2 ;;
    --counterexample) CEX_NAME=${2:?}; shift 2 ;;
    --expect-fail) CEX_EXPECT=${2:?}; shift 2 ;;
    --break-stub) BREAK_STUB=${2:?}; shift 2 ;;
    --unknown-stub-cmd) UNKNOWN_STUB=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "不认识的参数：$1（--help 看用法）" ;;
  esac
done

command -v python3 >/dev/null 2>&1 || die "没有 python3（沙箱与 JSON 都靠它）。本地跑请进 WSL：wsl.exe -e bash scripts/run-sandbox-local.sh"
command -v timeout >/dev/null 2>&1 || die "没有 timeout"

# ---- 并发闸（T00 补）：两个沙箱并发会互相腐坏用例树（2026-11-06 实测 47×127），
# 串行是硬约束。flock 拿不到就当场拒绝，绝不排队等着错。
mkdir -p "$REPO/reports"
exec 9>>"$REPO/reports/.sandbox-lock"
flock -n 9 || die "另一个沙箱实例正在跑（reports/.sandbox-lock 被占）。串行是硬约束，等它结束再跑。"

# ---- 引擎判定：Linux/WSL 里直接跑；从 Git Bash 发起就折算路径交给 WSL 重跑自己 ----
case "$(uname -s 2>/dev/null)" in
  Linux) : ;;
  *MINGW*|*MSYS*)
    command -v cygpath >/dev/null 2>&1 || die "Git Bash 里没有 cygpath，没法折算 WSL 路径"
    command -v wsl.exe >/dev/null 2>&1 || die "找不到 wsl.exe；请装 WSL 或直接在 WSL 里跑"
    win=$(cygpath -w "$REPO")
    drive=$(printf '%s' "$win" | cut -c1 | tr 'A-Z' 'a-z')
    wpath="/mnt/$drive$(printf '%s' "${win#?:}" | tr '\\' '/')"
    log "从 Git Bash 发起，交给 WSL 重跑：$wpath"
    exec wsl.exe -e bash -c "cd '$wpath' && bash scripts/run-sandbox-local.sh $(printf '%q ' "$@")"
    ;;
  *) die "不认识的执行环境：$(uname -s 2>/dev/null)。本地沙箱要 Linux/WSL。" ;;
esac

[ -f "$REPO/pdd.sh" ] && [ -f "$REPO/sandbox/sbx.sh" ] || die "仓库里找不到 pdd.sh / sandbox/sbx.sh：$REPO"
command -v sha256sum >/dev/null 2>&1 || die "没有 sha256sum"
command -v git >/dev/null 2>&1 && GIT_HEAD=$(git -C "$REPO" rev-parse HEAD 2>/dev/null) || GIT_HEAD=""
ENGINE_DESC=$(printf 'bash=%s python3=%s kernel=%s' "$(bash --version | head -1 | awk '{print $4}')" \
  "$(python3 -c 'import platform;print(platform.python_version())')" "$(uname -r)")

# ---- 分类器（python 单源：分类、自检、聚合三用） ----
CLASSIFY_PY=$(mktemp "${TMPDIR:-/tmp}/t00-classify.XXXXXX.py")
trap 'rm -f "$CLASSIFY_PY"' EXIT
cat >"$CLASSIFY_PY" <<'PYEOF'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T00 门禁分类器：sbx.sh 日志 -> verdict + 机读 JSON。聚合模式产出 harness-result.json。

verdict 词汇表（run-sandbox-local.sh 的退出码语义跟着它走）：
  pass           全过且执行数相符
  cases-failed   有用例失败
  only-unknown   ONLY 选中的用例不在表里
  count-mismatch 执行数与登记数不符
  infra          基础设施错误（输入/桩缺失、自检不过）
  timeout        外层强制超时（进程被 kill）
  no-end-marker  日志里没有 SBX_DONE（半途死亡）
"""
import json
import os
import re
import sys

CASE_RE = re.compile(
    r"^CASE name=(\S+) ok=(\d) rc=(\S+) lit=(\S*) marker=(\S+) taps=(\d+) backs=(\d+) "
    r"pushes=(\d+) close=(\d) duration_ms=(\d+)\s*$")
SUM_RE = re.compile(
    r"^SANDBOX_SUMMARY expected=(\d+) executed=(\d+) failed=(\d+) skipped=(\d+) "
    r"infra_error=(\d+) size=(\S+) only=(\S*)\s*$")


def parse_log(path):
    cases, summary, done, infra = [], None, False, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "SBX_DONE":
                done = True
                continue
            m = CASE_RE.match(line)
            if m:
                cases.append(dict(zip(("name", "ok", "rc", "lit", "marker", "taps",
                                       "backs", "pushes", "close", "duration_ms"),
                                      m.groups())))
                continue
            s = SUM_RE.match(line)
            if s:
                summary = dict(zip(("expected", "executed", "failed", "skipped",
                                    "infra_error", "size", "only"), s.groups()))
                continue
            if line.startswith("SANDBOX_INFRA_ERROR"):
                infra.append(line)
    return cases, summary, done, infra


def classify(log_path, sbx_rc, outer_rc, expected_default):
    cases, summary, done, infra = parse_log(log_path)
    expected = expected_default
    executed = len(cases)
    failed = sum(1 for c in cases if c["ok"] == "0")
    if summary:
        expected = int(summary["expected"])
        executed = int(summary["executed"])
        failed = int(summary["failed"])
    # 账目交叉核对：summary 的 executed/failed 必须和 CASE 行对得上，对不上就是
    # 日志被动过/打印被吞 —— 两种口径的任何分歧都按执行数不符处理，不许绿。
    ledger_mismatch = bool(summary) and (
        int(summary["executed"]) != len(cases) or int(summary["failed"]) != failed)
    if outer_rc == 124:
        verdict = "timeout"
    elif sbx_rc == 2 or any("不在用例表里" in i for i in infra):
        verdict = "only-unknown"
    elif sbx_rc == 3 or infra:
        verdict = "infra"
    elif not done:
        verdict = "no-end-marker"
    elif sbx_rc == 4 or executed != expected or ledger_mismatch:
        verdict = "count-mismatch"
    elif failed > 0:
        verdict = "cases-failed"
    elif sbx_rc == 0 and executed == expected and failed == 0:
        verdict = "pass"
    else:
        verdict = "unknown"
    return verdict, {"cases": cases, "summary": summary, "done": done,
                     "infra": infra, "expected": expected,
                     "executed": executed, "failed": failed}


def cmd_classify(a):
    verdict, info = classify(a.log, a.sbx_rc, a.outer_rc, a.expected)
    out = {
        "kind": "counterexample" if a.counterexample else "sandbox-run",
        "counterexample": a.counterexample or None,
        "expect_fail": a.expect_fail or None,
        "as_expected": (verdict == a.expect_fail) if a.expect_fail else None,
        "verdict": verdict,
        "size": a.size, "only": a.only or None,
        "expected": info["expected"], "executed": info["executed"],
        "failed": info["failed"], "skipped": 0,
        "infra_error": len(info["infra"]),
        "end_marker": info["done"],
        "exit_code": a.sbx_rc, "outer_exit_code": a.outer_rc,
        "started": a.started, "ended": a.ended, "duration_ms": a.duration_ms,
        "engine": a.engine, "git_head": a.git_head or None,
        # a.shafile 是路径，不是 JSON 文本；直接 loads(路径) 会把 '/' 当 JSON 解析报错
        # （2026-11-06 首跑实测：Expecting value: line 1 column 1）。
        "source_sha256": json.load(open(a.shafile, encoding="utf-8")) if a.shafile else {},
        "cases": info["cases"],
        "infra_lines": info["infra"],
        "artifacts": {"log": a.log, "run_root": a.run_root, "staged_input": a.staged},
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("GATE_VERDICT verdict=%s executed=%d failed=%d expected=%d end_marker=%s"
          % (verdict, info["executed"], info["failed"], info["expected"], info["done"]))
    return 0 if out["as_expected"] in (None, True) and verdict == "pass" or out["as_expected"] is True else 1


def cmd_selfcheck(a):
    import tempfile
    vecs = []
    def add(name, want, lines, sbx_rc, outer_rc, expected):
        vecs.append((name, want, "\n".join(lines) + "\n", sbx_rc, outer_rc, expected))
    two = ["CASE name=a ok=1 rc=0 lit=3 marker=yes taps=3 backs=1 pushes=1 close=1 duration_ms=5",
           "CASE name=b ok=1 rc=0 lit=3 marker=yes taps=3 backs=1 pushes=1 close=1 duration_ms=5"]
    fail = two[:1] + ["CASE name=b ok=0 rc=6 lit= marker=no taps=0 backs=0 pushes=0 close=0 duration_ms=5"]
    add("干净全过", "pass", two + ["SANDBOX_SUMMARY expected=2 executed=2 failed=0 skipped=0 infra_error=0 size=720x1280 only=", "SBX_DONE"], 0, 0, 2)
    add("有用例失败", "cases-failed", fail + ["SANDBOX_SUMMARY expected=2 executed=2 failed=1 skipped=0 infra_error=0 size=720x1280 only=", "SBX_DONE"], 1, 0, 2)
    add("丢结束标记", "no-end-marker", two + ["SANDBOX_SUMMARY expected=2 executed=2 failed=0 skipped=0 infra_error=0 size=720x1280 only="], 0, 0, 2)
    add("执行数不符", "count-mismatch", two[:1] + ["SANDBOX_SUMMARY expected=2 executed=1 failed=0 skipped=0 infra_error=0 size=720x1280 only=", "SBX_DONE"], 4, 0, 2)
    add("坏 ONLY", "only-unknown", ["SANDBOX_INFRA_ERROR: ONLY=nope 不在用例表里（共 47 例）"], 2, 0, 1)
    add("强制超时", "timeout", ["CASE name=a ok=1 rc=0 lit=3 marker=yes taps=1 backs=0 pushes=0 close=0 duration_ms=1"], 0, 124, 47)
    add("基础设施错误", "infra", ["SANDBOX_INFRA_ERROR: 输入目录里缺桩 bin/adb"], 3, 0, 47)
    add("summary 与 CASE 行矛盾", "count-mismatch", two[:1] + ["SANDBOX_SUMMARY expected=2 executed=2 failed=0 skipped=0 infra_error=0 size=720x1280 only=", "SBX_DONE"], 0, 0, 2)
    bad = 0
    for name, want, text, sbx_rc, outer_rc, expected in vecs:
        fd, p = tempfile.mkstemp(suffix=".log")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        got, _ = classify(p, sbx_rc, outer_rc, expected)
        os.unlink(p)
        ok = got == want
        print("%-24s want=%-14s got=%-14s %s" % (name, want, got, "ok" if ok else "FAIL"))
        bad += 0 if ok else 1
    print("SELF_CHECK %s" % ("OK" if bad == 0 else "FAIL(%d)" % bad))
    return 1 if bad else 0


def cmd_aggregate(a):
    frags = []
    for dirpath, _, files in os.walk(a.root):
        if "result.json" in files:
            with open(os.path.join(dirpath, "result.json"), encoding="utf-8") as f:
                try:
                    frags.append(json.load(f))
                except Exception as e:
                    print("聚合告警：坏 JSON 跳过 %s (%s)" % (dirpath, e), file=sys.stderr)
    runs = [f for f in frags if f.get("kind") == "sandbox-run" and not f.get("counterexample")]
    negs = [f for f in frags if f.get("kind") == "negative-control"]
    cexs = [f for f in frags if f.get("kind") == "counterexample"]
    runs.sort(key=lambda f: f.get("size") or "")
    reasons = []
    if not runs:
        reasons.append("没有 sandbox-run 结果")
    for r in runs:
        if r.get("verdict") != "pass":
            reasons.append("sandbox-run %s verdict=%s" % (r.get("size"), r.get("verdict")))
        elif r.get("executed") != 47 or r.get("expected") != 47:
            reasons.append("sandbox-run %s 执行数 %d/%d" % (r.get("size"), r.get("executed"), r.get("expected")))
    if not negs:
        reasons.append("没有 negative-control 结果")
    for n in negs:
        if (n.get("executed"), n.get("killed"), n.get("survived"), n.get("infra_error")) != (11, 11, 0, 0):
            reasons.append("negative-control executed=%s killed=%s survived=%s infra=%s"
                           % (n.get("executed"), n.get("killed"), n.get("survived"), n.get("infra_error")))
    want_cex = {"bad-only", "forced-timeout", "missing-end-marker", "unknown-stub-cmd"}
    got_cex = {c.get("counterexample") for c in cexs}
    for c in sorted(want_cex - got_cex):
        reasons.append("缺反例：%s" % c)
    for c in cexs:
        if c.get("as_expected") is not True:
            reasons.append("反例 %s 未按预期失败（verdict=%s）" % (c.get("counterexample"), c.get("verdict")))
    sha = {}
    for f in frags:
        for k, v in (f.get("source_sha256") or {}).items():
            sha.setdefault(k, v)
    heads = {f.get("git_head") for f in frags if f.get("git_head")}
    gate_pass = not reasons
    out = {
        "schema": "pdd-t00-harness-result/1",
        "gate": "G0a",
        "pass": gate_pass,
        "fail_reasons": reasons,
        "git_head": sorted(heads)[0] if len(heads) == 1 else (sorted(heads) or [None]),
        "source_sha256": sha,
        "expected": {"sandbox_cases_per_size": 47, "sizes": sorted({r.get("size") for r in runs}),
                     "negative_controls": 11, "counterexamples": sorted(want_cex)},
        "executed": {"sandbox_total": sum(r.get("executed") or 0 for r in runs),
                     "negative_controls": sum(n.get("executed") or 0 for n in negs),
                     "counterexamples": len(cexs)},
        "failed": sum(r.get("failed") or 0 for r in runs),
        "skipped": 0,
        "infra_error": sum(r.get("infra_error") or 0 for r in runs)
                       + sum(n.get("infra_error") or 0 for n in negs),
        "runs": runs, "negative_controls": negs, "counterexamples": cexs,
        "durations_ms": {"sandbox": sum(r.get("duration_ms") or 0 for r in runs),
                         "negative_controls": sum(n.get("duration_ms") or 0 for n in negs)},
        "artifacts": sorted({p for f in frags for p in (f.get("artifacts") or {}).values() if p}),
        "gaps": [
            "47 例的期望值以「计数 + 日志字样」为准：推送次数（TITLE 行计数）与完整有序动作序列"
            "（逐动作 trace）没有逐例断言，baseline 只覆盖其中一部分 —— T15 换 fixture 驱动 + "
            "精确 trace 时补齐（tasks.md T00/T15、acceptance.md 第 6/7 节）。",
            "PIL 兼容层是沙箱基础设施（sandbox/pylib）：pdd.sh 的 band/pill 裁片像素不进任何判据"
            "（OCR 桩按文件名回 TSV），但真实 Pillow 语义已在 selftest 里对齐；换真 OCR 前应重验。",
        ],
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("GATE_SUMMARY pass=%s runs=%d neg=%d cex=%d reasons=%d"
          % (gate_pass, len(runs), len(negs), len(cexs), len(reasons)))
    for r in reasons:
        print("  - %s" % r)
    return 0 if gate_pass else 1


def main():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify")
    c.add_argument("--log", required=True)
    c.add_argument("--sbx-rc", type=int, required=True)
    c.add_argument("--outer-rc", type=int, default=0)
    c.add_argument("--expected", type=int, default=47)
    c.add_argument("--size", default="")
    c.add_argument("--only", default="")
    c.add_argument("--counterexample", default="")
    c.add_argument("--expect-fail", default="")
    c.add_argument("--started", default="")
    c.add_argument("--ended", default="")
    c.add_argument("--duration-ms", type=int, default=0)
    c.add_argument("--engine", default="")
    c.add_argument("--git-head", default="")
    c.add_argument("--shafile", default="")
    c.add_argument("--run-root", default="")
    c.add_argument("--staged", default="")
    c.add_argument("--out", required=True)
    c.set_defaults(func=cmd_classify)
    s = sub.add_parser("selfcheck")
    s.set_defaults(func=cmd_selfcheck)
    g = sub.add_parser("aggregate")
    g.add_argument("--root", required=True)
    g.add_argument("--out", required=True)
    g.set_defaults(func=cmd_aggregate)
    a = p.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
PYEOF

# ---- 模式分派 ----
if [ "$MODE" = selfcheck ]; then
  exec python3 "$CLASSIFY_PY" selfcheck
fi
if [ "$MODE" = aggregate ]; then
  [ -d "$AGG_DIR" ] || die "聚合目录不存在：$AGG_DIR"
  [ -n "$AGG_OUT" ] || { AGG_OUT="$REPO/reports/harness-result.json"; mkdir -p "$(dirname "$AGG_OUT")"; }
  exec python3 "$CLASSIFY_PY" aggregate --root "$AGG_DIR" --out "$AGG_OUT"
fi

# ---- 源清单（哈希在开工时就定死，写进每份 result.json） ----
SHA_FILE=$(mktemp "${TMPDIR:-/tmp}/t00-sha.XXXXXX.json")
trap 'rm -f "$CLASSIFY_PY" "$SHA_FILE"' EXIT
{
  printf '{\n'
  first=1
  for f in pdd.sh sandbox/sbx.sh sandbox/bin/adb sandbox/bin/tesseract sandbox/bin/curl \
           sandbox/pylib/PIL/__init__.py sandbox/pylib/PIL/Image.py sandbox/pylib/PIL/ImageOps.py \
           sandbox/pylib/selftest.py scripts/run-sandbox-local.sh; do
    h=$(sha256sum "$REPO/$f" | awk '{print $1}')
    [ $first = 1 ] || printf ',\n'
    printf '  "%s": "%s"' "$f" "$h"
    first=0
  done
  printf '\n}\n'
} >"$SHA_FILE" || die "源哈希算不出来"

# ---- 铺装输入目录：CRLF 全部抹平 + 语法检查 + 兼容层自检 ----
TS=$(date -u +%Y%m%dT%H%M%SZ)
ART=${ARTDIR:-$REPO/reports/t00/$TS-$SIZE}
mkdir -p "$ART" || die "产物目录建不起来：$ART"
IN=$ART/in
RUNROOT=$ART/run
LOG=$ART/sandbox-$SIZE.log
mkdir -p "$IN/bin" "$RUNROOT" || die "铺装目录建不起来：$ART"
tr -d '\r' <"$REPO/pdd.sh" >"$IN/pdd.sh"
tr -d '\r' <"$REPO/sandbox/sbx.sh" >"$IN/sbx.sh"
for s in adb tesseract curl; do
  tr -d '\r' <"$REPO/sandbox/bin/$s" >"$IN/bin/$s" || die "桩 $s 铺装失败"
  chmod 755 "$IN/bin/$s"
done
mkdir -p "$IN/pylib/PIL"
for p in "$REPO"/sandbox/pylib/PIL/*.py; do
  # 必须保住 PIL/ 这一层目录：basename 平铺会让 pylib/PIL 变成空命名空间包，
  # selftest 报 cannot import name 'Image'（2026-11-06 首跑实测踩过）。
  tr -d '\r' <"$p" >"$IN/pylib/PIL/$(basename "$p")" || die "兼容层 $p 铺装失败"
done
tr -d '\r' <"$REPO/sandbox/pylib/selftest.py" >"$IN/pylib/selftest.py" || die "兼容层 selftest 铺装失败"
for f in "$IN/sbx.sh" "$IN/pdd.sh" "$IN/bin/adb" "$IN/bin/tesseract" "$IN/bin/curl"; do
  bash -n "$f" || die "语法检查不过：$f"
done
echo STUBS_OK
python3 "$IN/pylib/selftest.py" >"$ART/pil-selftest.log" 2>&1 \
  || { cat "$ART/pil-selftest.log" >&2; die "PIL 兼容层自检失败（见上）"; }
log "铺装完成：$IN"

# ---- 反例注入（只动 staged 拷贝，绝不碰仓库原件） ----
if [ -n "$BREAK_STUB" ]; then
  case "$BREAK_STUB" in
    adb|tesseract|curl) rm -f "$IN/bin/$BREAK_STUB" ;;
    *) die "--break-stub 只认 adb/tesseract/curl" ;;
  esac
  log "反例注入：拿掉桩 $BREAK_STUB（丢结束标记/基础设施错误的真实触发）"
fi
if [ "$UNKNOWN_STUB" = 1 ]; then
  sed -i 's#adb_shell input tap#adb_shell input frobnicate#' "$IN/pdd.sh"
  grep -q 'adb_shell input frobnicate' "$IN/pdd.sh" || die "反例注入失败：未知桩命令没种进去"
  log "反例注入：pdd.sh 拷贝里 input tap → input frobnicate（桩严格模式必须咬住）"
fi

# ---- 跑 ----
log "开跑：size=$SIZE only=${ONLY:-<全部>} timeout=${TIMEOUT}s"
STARTED=$(date -u +%Y%m%dT%H%M%SZ)
T0=$(date +%s%N)
set +e
# 不能写 `SBX_IN=… ${ONLY:+ONLY=$ONLY} timeout …`：参数展开的结果不会被 bash
# 重新识别为赋值前缀，ONLY 非空时 "ONLY=locked" 会被当命令名（127，实测踩过）。
export SBX_IN=$IN SBX_ROOT=$RUNROOT SBX_SIZE=$SIZE
[ -n "$ONLY" ] && export ONLY
timeout "$TIMEOUT" bash "$IN/sbx.sh" >"$LOG" 2>&1
SBX_RC=$?
set -e
T1=$(date +%s%N)
DUR_MS=$(( (T1 - T0) / 1000000 ))
ENDED=$(date -u +%Y%m%dT%H%M%SZ)
log "沙箱退出码=$SBX_RC 用时=${DUR_MS}ms 日志=$LOG"
tail -n 6 "$LOG"

EXPECTED=47
[ -n "$ONLY" ] && EXPECTED=1
RESULT=$ART/result.json
set +e
python3 "$CLASSIFY_PY" classify \
  --log "$LOG" --sbx-rc "$SBX_RC" --outer-rc "$SBX_RC" --expected "$EXPECTED" \
  --size "$SIZE" --only "$ONLY" --counterexample "$CEX_NAME" --expect-fail "$CEX_EXPECT" \
  --started "$STARTED" --ended "$ENDED" --duration-ms "$DUR_MS" \
  --engine "$ENGINE_DESC" --git-head "$GIT_HEAD" --shafile "$SHA_FILE" \
  --run-root "$RUNROOT" --staged "$IN" --out "$RESULT"
PY_RC=$?
set -e
[ -n "$JSON_OUT" ] && { mkdir -p "$(dirname "$JSON_OUT")"; cp -f "$RESULT" "$JSON_OUT"; }
log "结果 JSON：$RESULT"
exit "$PY_RC"
