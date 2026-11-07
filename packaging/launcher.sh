#!/bin/sh
# T17 稳定启动器：一次解析 current 指针后 exec，运行中不重解析。
# 回滚只影响下一次启动；正在跑的进程不会中途换代码。
set -eu
ROOT="${PDDCHECK_ROOT:?PDDCHECK_ROOT 未设置}"
CUR=$(cat "$ROOT/current")
[ -n "$CUR" ] || { echo "current 指针为空" >&2; exit 78; }
if [ -e "$ROOT/paused" ]; then echo "paused：跳过本次" >&2; exit 0; fi
SITE="$ROOT/releases/$CUR/site"
[ -d "$SITE" ] || { echo "release $CUR 未展开（缺 site/）" >&2; exit 78; }
PY="${PDDCHECK_PYTHON:-python3}"
exec env PYTHONPATH="$SITE" "$PY" -m pddcheck.cli.app "$@"
