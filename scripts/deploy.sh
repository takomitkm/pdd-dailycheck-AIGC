#!/usr/bin/env bash
# 部署 sandbox 全绿的 pdd.sh 到 debian Desktop：先备份，再装，再验。
# 用法：bash deploy.sh <远端上的待部署文件路径> [<远端上的待部署配置路径>]
#       （默认 /tmp/pdd-deploy.sh 和 /tmp/pdd-ocr.conf）
# 配置文件这份跟 pdd.sh 不一样：11-01 起它在 .gitignore 里，仓库不带它，
# 主机 ~/Desktop/pdd-ocr.conf 就是唯一一份、调参在那里改。
# 所以这个脚本只处理「主机上还没有」这一种兜底情况（从 /tmp 拷一份过去）；已有就一个字不动。
set -e
REMOTE=${1:-/tmp/pdd-deploy.sh}
CONF=${2:-/tmp/pdd-ocr.conf}
D=/home/user/Desktop
TS=$(date +%m%d-%H%M)

[ -s "$REMOTE" ] || { echo "待部署文件不存在或为空：$REMOTE"; exit 1; }
tr -d '\015' <"$REMOTE" >"$REMOTE.lf" && mv "$REMOTE.lf" "$REMOTE"
bash -n "$REMOTE" || { echo "语法不过，不部署"; exit 1; }

if [ -f "$D/pdd.sh" ]; then
  cp -f "$D/pdd.sh" "$D/pdd.sh.bak-$TS"
  echo "旧版已备份 -> $D/pdd.sh.bak-$TS  md5=$(md5sum <"$D/pdd.sh.bak-$TS" | cut -c1-8)"
fi
install -m 700 "$REMOTE" "$D/pdd.sh"
echo "新版 md5=$(md5sum <"$D/pdd.sh" | cut -c1-8)  行数=$(wc -l <"$D/pdd.sh")  权限=$(stat -c '%a %U:%G' "$D/pdd.sh")"

# OCR 调用配置：仓库不带这份（11-01 进 .gitignore），主机那一份是唯一现役。
# 带来了且主机上还没有才装；主机已有就一个字不动，只把跟带来那一份的差异念出来。
if [ -s "$CONF" ]; then
  tr -d '\015' <"$CONF" >"$CONF.lf" && mv "$CONF.lf" "$CONF"
  if [ -f "$D/pdd-ocr.conf" ]; then
    echo "OCR 配置：$D/pdd-ocr.conf 已存在（md5=$(md5sum <"$D/pdd-ocr.conf" | cut -c1-8)），这次不动它。"
    if ! diff -q "$CONF" "$D/pdd-ocr.conf" >/dev/null; then
      echo "  和这次带来的 /tmp 那份不一样，不一样的行（< 带来的 / > 主机在用的）："
      diff "$CONF" "$D/pdd-ocr.conf" | grep -E '^[<>][[:space:]]*[A-Za-z_][A-Za-z0-9_]*=' || true
      echo "  想换成带来的这份：先在主机上 cp -a $D/pdd-ocr.conf $D/pdd-ocr.conf.bak-$TS，再 install -m 600 $CONF $D/pdd-ocr.conf"
    else
      echo "  内容和带来的这份一致。"
    fi
  else
    install -m 600 "$CONF" "$D/pdd-ocr.conf"
    echo "OCR 配置：已装 $D/pdd-ocr.conf 权限=$(stat -c '%a' "$D/pdd-ocr.conf") 键数=$(grep -cE '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=' "$D/pdd-ocr.conf")"
  fi
else
  echo "OCR 配置：没给到可读的 $CONF，跳过安装（pdd.sh 读不到文件就退回内建默认）。"
fi

# 暂停天数文件：不存在就建一个 0，让行为确定（0 = 正常跑）
if [ -f "$D/pdd-pause" ]; then
  echo "暂停文件已存在，内容=$(head -1 "$D/pdd-pause")，不动它"
else
  printf '0\n' >"$D/pdd-pause"
  chmod 600 "$D/pdd-pause"
  echo "已创建 $D/pdd-pause = 0（0 表示正常跑）"
fi

# 端点外置之后，"没配推送"是一个会静默通过的状态：当场说清楚，别等明早 10:00 才发现一条都没推。
if [ -r "$D/pdd-push.url" ]; then
  echo "推送端点：$D/pdd-push.url 可读，第一行长度 $(head -1 "$D/pdd-push.url" | tr -d ' \t\r\n' | wc -c)（值不打印）"
else
  echo "推送端点：读不到 $D/pdd-push.url —— 流程照跑，但一条都不会推。"
  echo '  要推：主机上 umask 077 后把端点写成这个文件的第一行'
fi

# 装了 pdd.sh 就得确认它能把这份配置读进那两条闸：拿一个不存在的子命令走一遍——
# 「读不动」和「值不成形」这两道 exit 78 挡在任何子命令之前，走得通就说明这套值全在校验范围内。
# 这条也不碰手机：adb 那一层只问 adb 在不在 PATH，不连设备。
echo "--- 配置自检（不存在的子命令，只走装载与校验这两步）---"
if conf_out=$(bash "$D/pdd.sh" __confcheck 2>&1); then
  echo "OK：装载与校验都过了（文件不存在时按内建默认过）"
else
  echo "配置自检失败 rc=$?："
  echo "$conf_out"
  echo "  —— 现在这份 $D/pdd.sh 明早 10:00 会原地停在 78，一枪都不开。先把上面那行改对再收工。"
  exit 1
fi

systemctl --user list-timers --all 2>/dev/null | grep -E 'pdd|NEXT' | head -3
echo "--- 本地语法复查 ---"
bash -n "$D/pdd.sh" && echo OK
