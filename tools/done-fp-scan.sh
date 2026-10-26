#!/usr/bin/env bash
# 只读扫描：`ALIAS_done` 那四个词到底会不会出现在"非终态屏"的证据帧里。
# 给 `proof_ok` 第三条救法（读到 done 那几个字就算页面进对了）数误报面用。
#
# 口径（读结果前先看这三句）：
#   1. 走整页 OCR 全文，**不做 `REGION_done` 闸门** —— 这是上界。词在全文里都不出现，
#      带闸门的判定必然也不出现；反过来不成立，所以真打红了得人工去看它在哪个坐标。
#   2. 默认跳过 `*-done-*.png`：那些帧本来就是"读到终态"那一步存下来的，不算误报面。
#      跳过模式是第 2 个参数，别以为它一直在。
#   3. psm 取线上整页那两档 6 和 11。band/pill 的裁片帧（`*band-*` / `*pill-*`）是同一屏的
#      局部放大，扫它们等于把同一帧数两遍，所以排除；总数由调用处给。
#
# 用法：bash tools/done-fp-scan.sh <证据根目录> [跳过模式，默认 -done-]
#
# 10-26 跑过一次全量：333 帧命中 7 帧，7 帧全落在活动页/终态屏（4 帧「5折 最高减15元 已使用」
# + 3 帧「今日已点亮」），另外 274 帧 0 命中。逐帧表和分母怎么来的在 docs/calibration.md 三。
set -u
root=${1:?用法: done-fp-scan.sh <证据根目录> [跳过模式]}
skip=${2:--done-}
pat='已点亮|明日再来|明天再来|已使用'
n=0; hits=0; crop=0
while IFS= read -r f; do
  b=$(basename "$f")
  case "$b" in *band-*|*pill-*) crop=$((crop+1)); continue ;; esac
  case "$b" in *"$skip"*) continue ;; esac
  n=$((n + 1))
  got=
  for p in 6 11; do
    t=$(tesseract "$f" - -l chi_sim --psm "$p" 2>/dev/null | grep -E "$pat")
    [ -n "$t" ] && got=$t
  done
  if [ -n "$got" ]; then
    hits=$((hits + 1)); echo "命中 $f"; printf '%s\n' "$got" | sed 's/^/    /'
  fi
done < <(find "$root" -name '*.png' | sort)
echo "done-fp-scan: 扫过 $n 帧，命中 $hits 帧（跳过裁片 $crop 帧，跳过模式 *${skip}*）"
