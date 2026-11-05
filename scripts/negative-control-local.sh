#!/usr/bin/env bash
# 负对照（本地版）：把某一处代码改坏，对应那条用例必须挂红。挂了就说明它真的在钉那段代码。
#
# 11 条变异的 sed 表达式/锚点/want/用例映射逐字保留自原 SSH 版（scripts/negative-control.sh
# 的历史版本）；变化只在执行层：不再 SSH 到 deb-h61，本地铺装 + env 隔离直跑，
# 并新增机器可判定契约（原版「没咬住」只打印、末尾永远成功——门禁据此被 T00 修掉）。
#
# 判定：每条 = executed(用例真的跑了) + killed(用例挂红)。11 条必须 executed=11、
# killed=11、survived=0、infra_error=0，否则退出非零。语法错/补丁没做成/超时一律 infra，
# 不算 killed（10-30 第一条假红教训）。
#
# 用法：bash scripts/negative-control-local.sh [--keep]   # --keep 保留工作目录供排查
set -u
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# 并发闸：与 run-sandbox-local 同一把锁（负对照会真跑 sbx.sh 用例）。
mkdir -p "$REPO/reports"
exec 9>>"$REPO/reports/.sandbox-lock"
flock -n 9 || { echo 'NEG-ERROR: 另一个沙箱实例正在跑，串行是硬约束'; exit 2; }
WORK=${NEG_WORK:-$(mktemp -d /tmp/t00-neg.XXXXXX)}
KEEP=0
[ "${1:-}" = --keep ] && KEEP=1
trap '[ $KEEP = 1 ] || rm -rf "$WORK"' EXIT

run_neg() { # $1=编号 $2=sed 表达式 $3=锚点正则 $4=yes(补丁后应还能 grep 到)/no(应 grep 不到) $5=用例名(默认同 $1)
  local nm=$1 expr=$2 pat=$3 want=$4 cs=${5:-$1}
  local dir=$WORK/$nm
  echo "===== 负对照：$nm（跑用例 $cs）"
  rm -rf "$dir"; mkdir -p "$dir/in/bin" "$dir/in/pylib/PIL"
  # 铺装：与 run-sandbox-local.sh 同一拼装（CRLF 抹平），再打变异补丁
  local f
  for f in pdd.sh sandbox/sbx.sh; do tr -d '\r' <"$REPO/$f" >"$dir/in/$(basename "$f")"; done
  for f in adb tesseract curl; do tr -d '\r' <"$REPO/sandbox/bin/$f" >"$dir/in/bin/$f"; chmod +x "$dir/in/bin/$f"; done
  for f in "$REPO"/sandbox/pylib/PIL/*.py; do tr -d '\r' <"$f" >"$dir/in/pylib/PIL/$(basename "$f")"; done
  tr -d '\r' <"$REPO/sandbox/pylib/selftest.py" >"$dir/in/pylib/selftest.py"
  sed -i "$expr" "$dir/in/pdd.sh" || { printf '%s\texecuted=0\tkilled=0\tinfra=补丁sed失败\n' "$nm"; INFRA=$((INFRA+1)); return 0; }
  local got=no
  grep -q -- "$pat" "$dir/in/pdd.sh" && got=yes
  [ "$got" = "$want" ] || { printf '%s\texecuted=0\tkilled=0\tinfra=锚点(%s≠%s)\n' "$nm" "$got" "$want"; INFRA=$((INFRA+1)); return 0; }
  if ! bash -n "$dir/in/pdd.sh"; then
    printf '%s\texecuted=0\tkilled=0\tinfra=补丁后语法错\n' "$nm"; INFRA=$((INFRA+1)); return 0
  fi
  # 只跑那一条用例（与 runner 同一隔离方式）
  local rc
  SBX_IN="$dir/in" SBX_ROOT="$dir/run" SBX_SIZE=${SBX_SIZE:-720x1280} ONLY="$cs" \
    timeout 600 bash "$dir/in/sbx.sh" >"$dir/out.txt" 2>&1
  rc=$?
  if [ $rc -eq 124 ]; then
    printf '%s\texecuted=0\tkilled=0\tinfra=超时\n' "$nm"; INFRA=$((INFRA+1)); return 0
  fi
  local case_line
  case_line=$(grep -E "^CASE name=$cs " "$dir/out.txt" | tail -1)
  if [ -z "$case_line" ]; then
    printf '%s\texecuted=0\tkilled=0\tinfra=无CASE行(rc=%s)\n' "$nm" "$rc"; INFRA=$((INFRA+1)); return 0
  fi
  local ok
  ok=$(printf '%s\n' "$case_line" | sed -n 's/.* ok=\([01]\) .*/\1/p')
  if [ "$ok" = 0 ]; then
    printf '%s\texecuted=1\tkilled=1\tinfra=0\n' "$nm"; KILLED=$((KILLED+1))
  else
    printf '%s\texecuted=1\tkilled=0\tinfra=0\t【存活！】\n' "$nm"; SURVIVED=$((SURVIVED+1))
  fi
  EXECUTED=$((EXECUTED+1))
}

# ---- 11 条变异（逐字保留自原版；锚点用「改前 0 命中」的串，want=yes 才有证据力） ----
EXECUTED=0; KILLED=0; SURVIVED=0; INFRA=0

run_neg browse-reenter-venue 's#text_present bag; then#false; then#' 'false; then' yes
run_neg bag-not-found '/^COORD_bag=/d' '^COORD_bag=' no
run_neg prize-take-coord '/^COORD_take=/d' '^COORD_take=' no
run_neg used-terminal 's|^  if text_present done; then$|  if text_present done_x; then|' 'text_present done_x' yes
run_neg used-band-psm6 's|^OCR_PSM_BAND_done=.*|OCR_PSM_BAND_done=7|' '^OCR_PSM_BAND_done=7$' yes
run_neg used-title-split 's|title="PDD 已使用"|title="PDD ✅"|' 'title="PDD 已使用"' no used-terminal
run_neg lit1-title 's|local title="PDD ✅"|local title="PDD 完"|' 'local title="PDD ✅"' no already-lit
run_neg entry-retry-guard 's#&& is_home_page "\$now"; then#\&\& false; then#' 'false; then' yes entry-swallowed-back
run_neg focus-fail-closed 's|print lbl;|print "";|; s|^  \[ "\$pkg" = "\$PKG" \] && return 0$|  [ -z "\$pkg" ] \&\& return 0|' '-z "\$pkg"' yes shade-slashless-focus
run_neg conf-not-loaded 's#^load_ocr_conf || {#true || {#' 'true || {' yes conf-band-psm6
run_neg push-metrics 's|%{exitcode} %{time_total}|negctl-blank|' 'negctl-blank' yes push-metrics-in-log

echo
printf 'NEG-SUMMARY executed=%d killed=%d survived=%d infra_error=%d\n' \
  "$EXECUTED" "$KILLED" "$SURVIVED" "$INFRA"
if [ "$EXECUTED" = 11 ] && [ "$KILLED" = 11 ] && [ "$SURVIVED" = 0 ] && [ "$INFRA" = 0 ]; then
  printf 'NEG-GATE pass\n'
  gate=pass; rc=0
else
  printf 'NEG-GATE fail（11 执行 / 11 杀死 / 0 存活 / 0 基础设施错 缺一即失败）\n'
  gate=fail; rc=1
fi
# 机读结果（聚合门禁消费；与 run-sandbox-local 的 result.json 同族）
outdir=$REPO/reports/t00/negative-control
mkdir -p "$outdir"
python3 - "$outdir/result.json" "$EXECUTED" "$KILLED" "$SURVIVED" "$INFRA" "$gate" "$REPO" <<'PY'
import json, subprocess, sys
out, executed, killed, survived, infra, gate, repo = sys.argv[1:]
sha = subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
json.dump({
    "kind": "negative-control",
    "gate": "G0a-negatives",
    "git_head": sha,
    "executed": int(executed), "killed": int(killed),
    "survived": int(survived), "infra_error": int(infra),
    "expected_mutations": 11,
    "verdict": gate,
}, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
PY
exit $rc
