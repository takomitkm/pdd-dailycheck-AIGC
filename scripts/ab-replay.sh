#!/usr/bin/env bash
# A/B：老字节和新字节在同一批存下来的帧上各跑一遍 replay --ocr，判据=输出逐字一样。
# 配置文件那套改动只许动"值从哪儿来"，不许动"判出来是什么"。两边都要**显式**给配置。
# （11-02 教训与两路写法见 docs/measurements/measured-AB-1102-routes.txt。）
#
# T00 修订（2026-11-06）：原版只把 DIFF 写进 status、永远退出 0——门禁据此修掉。
# 现在的契约：DIFF / 任一侧超时或 rc≠0 / 「两边同报错被 diff 判成相等」/ 场次数=0，
# 任何一项都让退出码非零。本地没有证据数据，比较逻辑用 --self-test 验证。
#
# 用法：
#   bash scripts/ab-replay.sh                 # 主机证据跑法（在 deb-h61 上或 SSH 内）
#   bash scripts/ab-replay.sh --self-test     # 本地契约自检（不碰任何真数据）
set -u

OLD=${OLD:-/home/user/Desktop/pdd.sh}
NEW=${NEW:-/tmp/pdd-ab-new.sh}
OUT=${OUT:-/tmp/pddab}
CONF_SIDE=${CONF_SIDE:-/nonexistent-pdd-ocr}
CONF_OLD=${CONF_OLD:-$CONF_SIDE}
TIMEOUT=${AB_TIMEOUT:-1800}
SESSIONS_GLOB=${SESSIONS_GLOB:-/home/user/Desktop/pdd-runs/*/*/}

# ---- 比较核心：判一场 = identical | diff | error（供主循环与自检共用） ----
judge_pair() { # $1=old输出文件 $2=new输出文件 $3=old rc $4=new rc $5=diff文件路径 -> 判定打到 stdout
  local or=$3 nr=$4
  if [ "$or" -ne 0 ] || [ "$nr" -ne 0 ]; then
    echo error; return 0
  fi
  if diff -q "$1" "$2" >/dev/null; then
    echo identical
  else
    diff "$1" "$2" >"$5" 2>/dev/null
    echo diff
  fi
}

main_host() {
  [ -f "$OLD" ] || { echo "AB-ERROR: 老字节不存在：$OLD"; exit 2; }
  [ -f "$NEW" ] || { echo "AB-ERROR: 新字节不存在：$NEW"; exit 2; }
  rm -rf "$OUT"; mkdir -p "$OUT"
  echo "start=$(date '+%F %T') old_md5=$(md5sum <"$OLD" | cut -c1-8) new_md5=$(md5sum <"$NEW" | cut -c1-8) conf_old=$CONF_OLD conf_side=$CONF_SIDE" >"$OUT/status"
  local n=0 ident=0 diffn=0 errn=0 d verdict
  for d in $SESSIONS_GLOB; do
    [ -f "$d/run.log" ] || continue
    n=$((n+1))
    d=$(echo "$d" | sed 's#/home/user/Desktop/pdd-runs/##; s#/#-#g')
    OCR_CONF_FILE=$CONF_OLD timeout "$TIMEOUT" bash "$OLD" replay "${d//-//}" --ocr >"$OUT/$d-old.txt" 2>&1
    local orc=$?
    echo "$d old rc=$orc $(date '+%T')" >>"$OUT/status"
    OCR_CONF_FILE=$CONF_SIDE timeout "$TIMEOUT" bash "$NEW" replay "${d//-//}" --ocr >"$OUT/$d-new.txt" 2>&1
    local nrc=$?
    echo "$d new rc=$nrc $(date '+%T')" >>"$OUT/status"
    verdict=$(judge_pair "$OUT/$d-old.txt" "$OUT/$d-new.txt" "$orc" "$nrc" "$OUT/$d.diff")
    case $verdict in
      identical) ident=$((ident+1)); echo "$d IDENTICAL 行数=$(wc -l <"$OUT/$d-old.txt")" >>"$OUT/status" ;;
      diff)      diffn=$((diffn+1)); echo "$d DIFF" >>"$OUT/status" ;;
      error)     errn=$((errn+1)); echo "$d ERROR(old=$orc new=$nrc)" >>"$OUT/status" ;;
    esac
  done
  echo "done=$(date '+%F %T')" >>"$OUT/status"
  printf 'AB-SUMMARY sessions=%d identical=%d diff=%d error=%d\n' "$n" "$ident" "$diffn" "$errn"
  [ "$n" -gt 0 ] && [ "$diffn" = 0 ] && [ "$errn" = 0 ] || exit 1
  exit 0
}

# ---- 本地契约自检：假脚本 + 假会话，验证 judge_pair 与主循环退出契约 ----
self_test() {
  local w
  w=$(mktemp -d /tmp/t00-ab.XXXXXX)
  trap 'rm -rf "$w"' EXIT
  cat >"$w/old.sh" <<'EOF'
#!/usr/bin/env bash
# 用法：old.sh replay <会话目录> --ocr ；行为由会话目录里的 want 文件决定
d=$2
want=$(cat "$d/want" 2>/dev/null || echo identical)
case $want in
  identical) printf 'replay A\nlines %s\n' "$(basename "$d")" ;;
  diff)      printf 'replay OLD-SIDE\n' ;;
  fail)      echo 'boom' >&2; exit 3 ;;
esac
exit 0
EOF
  cat >"$w/new.sh" <<'EOF'
#!/usr/bin/env bash
d=$2
want=$(cat "$d/want" 2>/dev/null || echo identical)
case $want in
  identical) printf 'replay A\nlines %s\n' "$(basename "$d")" ;;
  diff)      printf 'replay NEW-SIDE\n' ;;
  fail)      echo 'boom' >&2; exit 3 ;;
esac
exit 0
EOF
  chmod +x "$w/old.sh" "$w/new.sh"
  local pass=0 fail=0 v
  check() { # $1=场景名 $2=期望 $3=实际
    if [ "$2" = "$3" ]; then pass=$((pass+1)); echo "  ok   $1=$3"
    else fail=$((fail+1)); echo "  FAIL $1 期望$2 实得$3"; fi
  }
  # 场景1：两边一致
  mkdir -p "$w/s1"; echo identical >"$w/s1/want"
  v=$(cd "$w" && judge_pair <(bash "$w/old.sh" replay "$w/s1" --ocr 2>&1) <(bash "$w/new.sh" replay "$w/s1" --ocr 2>&1) 0 0 /dev/null)
  check identical identical "$v"
  # 场景2：两边不一致
  mkdir -p "$w/s2"; echo diff >"$w/s2/want"
  v=$(cd "$w" && judge_pair <(bash "$w/old.sh" replay "$w/s2" --ocr 2>&1) <(bash "$w/new.sh" replay "$w/s2" --ocr 2>&1) 0 0 "$w/s2.diff")
  check diff diff "$v"
  # 场景3：两边同报错（rc 相同、输出相同）——必须 error，不许算 identical
  mkdir -p "$w/s3"; echo fail >"$w/s3/want"
  v=$(cd "$w" && judge_pair <(bash "$w/old.sh" replay "$w/s3" --ocr 2>&1) <(bash "$w/new.sh" replay "$w/s3" --ocr 2>&1) 3 3 /dev/null)
  check error error "$v"
  # 场景4：一侧超时（rc=124）
  v=$(cd "$w" && judge_pair /dev/null /dev/null 124 0 /dev/null)
  check error-timeout error "$v"
  # 场景5：零场次 → 主循环契约（直接断言表达式）
  n=0; ident=0; diffn=0; errn=0
  if [ "$n" -gt 0 ] && [ "$diffn" = 0 ] && [ "$errn" = 0 ]; then check zero-sessions fail pass
  else check zero-sessions fail fail; fi

  printf 'AB-SELFTEST pass=%d fail=%d\n' "$pass" "$fail"
  [ "$fail" = 0 ] || exit 1
  exit 0
}

case ${1:-} in
  --self-test) self_test ;;
  *) main_host ;;
esac
