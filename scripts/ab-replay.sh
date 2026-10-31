#!/usr/bin/env bash
# A/B：老字节（桌面上现役那份）和新字节（这次带来的那份）在同一批存下来的帧上各跑一遍 replay --ocr。
# 判据：两份输出逐字一样。配置文件那套改动只许动"值从哪儿来"，不许动"判出来是什么"。
# 新字节那一路显式指一个不存在的 OCR_CONF_FILE，逼它走内建默认 —— 不然主机桌面上要是已经有
# ~/Desktop/pdd-ocr.conf，这一跑比的就是"配置 vs 老硬编码"，不是这次要的"同一套值两条路"。
# 这一跑只证了一半，要两路都过才算"配置化没动判据"：
#   第一路（默认）      —— 新字节 + 没有配置文件 = 内建默认，对老硬编码
#   第二路（真装上去的）—— CONF_SIDE=/home/user/Desktop/pdd-ocr.conf OUT=/tmp/pddab2
# 第二路证的是"仓库里这份 conf 抄到主机上之后，判出来的还是原来那套"，也就是明早 10:00 那一跑走的路。
set -u
# 部署之后桌面上那份就是新字节了，所以 OLD 要能指到备份（第一跑时桌面上还是老字节，默认值正好）
OLD=${OLD:-/home/user/Desktop/pdd.sh}
NEW=/tmp/pdd-ab-new.sh
OUT=${OUT:-/tmp/pddab}
CONF_SIDE=${CONF_SIDE:-/nonexistent-pdd-ocr}
rm -rf "$OUT"; mkdir -p "$OUT"
echo "start=$(date '+%F %T') old_md5=$(md5sum <"$OLD" | cut -c1-8) new_md5=$(md5sum <"$NEW" | cut -c1-8) conf_side=$CONF_SIDE" >"$OUT/status"
for d in /home/user/Desktop/pdd-runs/*/*/; do
  [ -f "$d/run.log" ] || continue
  n=$(echo "$d" | sed 's#/home/user/Desktop/pdd-runs/##; s#/#-#g')
  timeout 1800 bash "$OLD" replay "$d" --ocr >"$OUT/$n-old.txt" 2>&1
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
