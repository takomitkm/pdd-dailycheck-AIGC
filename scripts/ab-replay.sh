#!/usr/bin/env bash
# A/B：老字节（桌面上现役那份）和新字节（这次带来的那份）在同一批存下来的帧上各跑一遍 replay --ocr。
# 判据：两份输出逐字一样。配置文件那套改动只许动"值从哪儿来"，不许动"判出来是什么"。
# 两边都要**显式**给配置文件，不许任何一侧默默读桌面上那一份。这条是 11-02 踩出来的：
# 老版本只给新字节那一侧 `OCR_CONF_FILE=$CONF_SIDE`，老字节那一侧空着跑，于是它读的是
# `~/Desktop/pdd-ocr.conf`。我在跑到第 4 场时把 `VLM_BACKEND=local` 那行启用，老字节
# `cc376aa3` 的名单里没有这个键，当场 78 停，后面几场全变 DIFF —— 一个跟改动无关的动作把整跑废了。
# 两路的正确写法：
#   第一路（纯比字节）—— CONF_OLD=CONF_SIDE=/nonexistent-pdd-ocr，两边都走内建默认，
#                        桌面上那份配置怎么改都影响不到这一跑
#   第二路（真装上去的）—— CONF_SIDE=/home/user/Desktop/pdd-ocr.conf（新字节读现役那份 22 个键），
#                        CONF_OLD 指到启用那行**之前**的快照（老字节认得它），
#                        这一路证的才是"启用 VLM_BACKEND 这行没动判据"，也就是明早 10:00 那条路
set -u
# 部署之后桌面上那份就是新字节了，所以 OLD 要能指到备份（第一跑时桌面上还是老字节，默认值正好）
OLD=${OLD:-/home/user/Desktop/pdd.sh}
NEW=/tmp/pdd-ab-new.sh
OUT=${OUT:-/tmp/pddab}
CONF_SIDE=${CONF_SIDE:-/nonexistent-pdd-ocr}
CONF_OLD=${CONF_OLD:-$CONF_SIDE}
rm -rf "$OUT"; mkdir -p "$OUT"
echo "start=$(date '+%F %T') old_md5=$(md5sum <"$OLD" | cut -c1-8) new_md5=$(md5sum <"$NEW" | cut -c1-8) conf_old=$CONF_OLD conf_side=$CONF_SIDE" >"$OUT/status"
for d in /home/user/Desktop/pdd-runs/*/*/; do
  [ -f "$d/run.log" ] || continue
  n=$(echo "$d" | sed 's#/home/user/Desktop/pdd-runs/##; s#/#-#g')
  OCR_CONF_FILE=$CONF_OLD timeout 1800 bash "$OLD" replay "$d" --ocr >"$OUT/$n-old.txt" 2>&1
  echo "$n old rc=$? $(date '+%T')" >>"$OUT/status"
  OCR_CONF_FILE=$CONF_SIDE timeout 1800 bash "$NEW" replay "$d" --ocr >"$OUT/$n-new.txt" 2>&1
  echo "$n new rc=$? $(date '+%T')" >>"$OUT/status"
  if diff -q "$OUT/$n-old.txt" "$OUT/$n-new.txt" >/dev/null; then
    echo "$n IDENTICAL 行数=$(wc -l <"$OUT/$n-old.txt")" >>"$OUT/status"
  else
    echo "$n DIFF" >>"$OUT/status"
    diff "$OUT/$n-old.txt" "$OUT/$n-new.txt" >"$OUT/$n.diff"
  fi
done
echo "done=$(date '+%F %T')" >>"$OUT/status"
