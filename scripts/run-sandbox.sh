#!/usr/bin/env bash
# 把桩沙箱推到主机的 /tmp/pddsandbox/in 并跑全矩阵。不碰手机：PATH 里只有桩 adb。
#
#   bash scripts/run-sandbox.sh                        # 720x1280，全 41 例
#   SBX_SIZE=1440x2560 bash scripts/run-sandbox.sh     # 同一份标定数据换一块屏
#   ONLY=happy-ocr bash scripts/run-sandbox.sh         # 只跑一例
#
# 验收：末行「失败用例数: 0」，且头行的 屏= 是你给的那块。
# 两跑共用 /tmp/pddsandbox/run 和 $SBX_EVENTS，会撞出一堆假失败，所以这里上锁。
set -u
H=user@192.168.1.102
SS=(ssh -4 -o ConnectTimeout=10 deb-h61)
SCP=(scp -4 -q -o ConnectTimeout=10)
SRC=${SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
SIZE=${SBX_SIZE:-720x1280}
[ -f "$SRC/pdd.sh" ] && [ -f "$SRC/sandbox/sbx.sh" ] || { echo "找不到仓库里的 pdd.sh / sandbox/sbx.sh：$SRC"; exit 1; }

# 抢锁：mkdir 是原子的，比数进程可靠（ps 的计数会把 ssh 自己那条命令行算进去）
"${SS[@]}" 'mkdir /tmp/pddsandbox.lock' 2>/dev/null || {
  echo "/tmp/pddsandbox.lock 已经存在 —— 有另一跑在跑，或者上一跑崩了没清扫。"
  echo "确认没有别的沙箱在跑之后：ssh deb-h61 rmdir /tmp/pddsandbox.lock"
  exit 1
}
trap '"${SS[@]}" "rmdir /tmp/pddsandbox.lock" >/dev/null 2>&1' EXIT

"${SS[@]}" 'rm -rf /tmp/pddsandbox; mkdir -p /tmp/pddsandbox/in/bin' || exit 1
"${SCP[@]}" "$SRC/sandbox/sbx.sh" "$H:/tmp/pddsandbox/in/" || exit 1
"${SCP[@]}" "$SRC/sandbox/bin/adb" "$SRC/sandbox/bin/tesseract" "$SRC/sandbox/bin/curl" \
  "$H:/tmp/pddsandbox/in/bin/" || exit 1
"${SCP[@]}" "$SRC/pdd.sh" "$H:/tmp/pddsandbox/in/pdd.sh" || exit 1

"${SS[@]}" "cd /tmp/pddsandbox/in && for f in sbx.sh pdd.sh bin/adb bin/tesseract bin/curl; do tr -d '\015' < \$f > t && mv t \$f; done
chmod 755 bin/*
bash -n sbx.sh && bash -n pdd.sh && bash -n bin/adb && bash -n bin/tesseract && bash -n bin/curl && echo STUBS_OK
export SBX_SIZE='$SIZE' ONLY='${ONLY:-}'
timeout 900 bash sbx.sh 2>&1 | tail -60"
echo "RUNSANDBOX_OK 屏=$SIZE"
