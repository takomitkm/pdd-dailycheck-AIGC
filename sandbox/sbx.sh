#!/usr/bin/env bash
# 桩沙箱：不碰手机，把同仓库那份 pdd.sh 的分支矩阵走一遍（39 例）。
# 推荐从本机跑 scripts/run-sandbox.sh，它会连上传带加锁一起办了。
# 直接在主机上跑：bash /tmp/pddsandbox/in/sbx.sh        # 全跑
#                ONLY=happy-ocr bash .../sbx.sh      # 只跑一个
#                SBX_SIZE=1440x2560 bash .../sbx.sh  # 换一块屏，用例几何自动折算
set -u

IN=${SBX_IN:-/tmp/pddsandbox/in}
SBX=${SBX_ROOT:-/tmp/pddsandbox/run}
SRC=$IN/pdd.sh
FAILED=0
rm -rf "$SBX"; mkdir -p "$SBX/bin" "$SBX/farm"
cp -f "$IN"/bin/adb "$IN"/bin/tesseract "$IN"/bin/curl "$SBX/bin/"
chmod 755 "$SBX"/bin/*

# 被测的那块"屏"要多大有多大：SBX_SIZE 同时决定桩 adb 报的点空间和桩截图的尺寸。
# 用例里的 row 坐标一律按 720x1280 那套写死，跑别的尺寸时由 sx/sy 折算过去 ——
# 这样"同一份标定数据换一块屏"必须给出完全相同的判定（rc/点亮状态/点几下/BACK 几下），
# 换分辨率还能用就是靠这条来钉。1440x2560 是 2 倍，折算全是整数，比对结果没有取舍歧义。
SBX_SIZE=${SBX_SIZE:-720x1280}
SBX_W=${SBX_SIZE%x*}; SBX_H=${SBX_SIZE#*x}
RSX=$(awk -v w="$SBX_W" 'BEGIN{printf "%.6f", w/720}')
RSY=$(awk -v h="$SBX_H" 'BEGIN{printf "%.6f", h/1280}')
sx() { awk -v v="$1" -v s="$RSX" 'BEGIN{printf "%d", v*s+0.5}'; }
sy() { awk -v v="$1" -v s="$RSY" 'BEGIN{printf "%d", v*s+0.5}'; }
export SBX_SIZE

python3 - "$SBX/shot.png" "${SBX_W:-720}" "${SBX_H:-1280}" <<'PY'
import sys
from PIL import Image
Image.new("RGB", (int(sys.argv[2]), int(sys.argv[3])), (200, 30, 40)).save(sys.argv[1])
PY
[ -s "$SBX/shot.png" ] || { echo "截图桩造不出来，停"; exit 1; }

# 工具农场：/usr/bin 等逐个软链，但 adb/tesseract/curl 不给 —— PATH 里永远只有桩，真 adb 不可能被碰到
for dir in /usr/local/sbin /usr/sbin /sbin /usr/local/bin /usr/bin /bin; do
  [ -d "$dir" ] || continue
  for f in "$dir"/*; do
    b=${f##*/}
    case "$b" in adb|tesseract|curl|scrcpy) continue ;; esac
    [ -e "$SBX/farm/$b" ] || ln -s "$f" "$SBX/farm/$b" 2>/dev/null
  done
done
mkdir -p "$SBX/bin_note" "$SBX/bin_noadb"
ln -s "$SBX/bin/adb" "$SBX/bin_note/adb"; ln -s "$SBX/bin/curl" "$SBX/bin_note/curl"
ln -s "$SBX/bin/tesseract" "$SBX/bin_noadb/tesseract"; ln -s "$SBX/bin/curl" "$SBX/bin_noadb/curl"

HDR=$'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'
ROW_N=0
row() { # row 文本 left top w h -> 一行 level=5 的 TSV（几何按 SBX_SIZE 折到那块屏上）
  # 行号必须按内容算：$(row ...) 在子 shell 里，递增全局计数器会被丢掉，
  # 于是所有行共用同一个 line_num，finder 把它们当成同一行拼成一长串。
  local l t w h id
  l=$(sx "$2"); t=$(sy "$3"); w=$(sx "$4"); h=$(sy "$5")
  id=$(printf '%s%s%s' "$1" "$l" "$t" | cksum | awk '{print $1 % 1000000 + 2}')
  printf '5\t1\t%s\t1\t%s\t1\t%s\t%s\t%s\t%s\t92\t%s\n' "$id" "$id" "$l" "$t" "$w" "$h" "$1"
}
tsvfile() { # tsvfile 路径 内容(已拼好的行)
  { printf '%s\n' "$HDR"; printf '%s' "${2:-}"; } >"$1"
}

base() {
  local dir=$1
  mkdir -p "$dir/runs"
  sed -e 's#^LAUNCH_WAIT=.*#LAUNCH_WAIT=0 STEP_WAIT=0 FIND_RETRY=2 FIND_INTERVAL=0 POPUP_MAX=2 POPUP_WAIT=0#' \
      -e 's#SWIPE_DUR=300 SWIPE_COUNT=20 SWIPE_WAIT=1#SWIPE_DUR=1 SWIPE_COUNT=2 SWIPE_WAIT=0#' \
      -e "s#^EVIDENCE_DIR=.*#EVIDENCE_DIR=$dir/runs#" \
      -e 's#^FIND_RETRY_bag=.*#FIND_RETRY_bag=2#' \
      -e 's#^FIND_INTERVAL_bag=.*#FIND_INTERVAL_bag=0#' \
      -e 's#^BROWSE_SECONDS=.*#BROWSE_SECONDS=2#' \
      -e 's#^BROWSE_DUR=.*#BROWSE_DUR=1#' \
      -e 's#^TOP_SWIPES=.*#TOP_SWIPES=1#' \
      -e 's#^SCROLL_TOP=.*#SCROLL_TOP=1#' \
      -e 's#^PROVE_MAX=.*#PROVE_MAX=2#' \
      -e "s#^PUSH_URL_FILE=.*#PUSH_URL_FILE=$dir/push.url#" \
      -e 's#^PUSH_URL=.*#PUSH_URL=http://stub.push/send#' \
      -e "s#^PAUSE_FILE=.*#PAUSE_FILE=$dir/pause#" \
      "$SRC" >"$dir/pdd.sh"
  # 上面每条 sed 都是靠行首锚点匹配的。锚点一旦失配，最坏的不是"跑得慢"，
  # 是推送端点 / 账本路径没被换掉 —— 39 个用例往真实 ServerChan 端点推 39 条，
  # 还会读写桌面上那个真账本。所以这里当场验一遍，不通过就直接停整个沙箱。
  grep -q 'PUSH_URL=http://stub.push/send' "$dir/pdd.sh" \
    || { echo "沙箱自检失败：PUSH_URL 没被替换，停（绝不往外推）"; exit 1; }
  grep -q "^PUSH_URL_FILE=$dir/push.url\$" "$dir/pdd.sh" \
    || { echo "沙箱自检失败：PUSH_URL_FILE 没被替换，停（万一 PUSH_URL 是空的就会去读桌面上那个真端点）"; exit 1; }
  grep -q "^PAUSE_FILE=$dir/pause\$" "$dir/pdd.sh" \
    || { echo "沙箱自检失败：PAUSE_FILE 没被替换，停（绝不碰桌面账本）"; exit 1; }
  grep -q 'SWIPE_COUNT=2 ' "$dir/pdd.sh" \
    || { echo "沙箱自检失败：SWIPE_* 那条 sed 没锚上（会按真实时长跑），停"; exit 1; }
  # 仓库是公开的，所以被测脚本本体里不许出现任何真凭据形态。这条和 githooks/pre-commit
  # 是两道独立的闸：钩子管提交，这条管"哪怕绕过钩子跑沙箱也会停"。
  if grep -qE 'sct[0-9a-zA-Z]{8,}|SCT[0-9a-zA-Z]{8,}|push\.ft07\.com|sct\.ftqq\.com' "$SRC"; then
    echo "沙箱自检失败：$SRC 里还有真推送端点/token，停（这仓库是公开的）"
    echo "端点应该写在主机的 ~/Desktop/pdd-push.url 里，脚本只读文件。"
    exit 1
  fi
}

W=$SBX/work
countfile() { # countfile 值1 值2 ...；空串 = 那一枪读不到进度行
  # 那行的措辞可以换（SBX_COUNT_WORD 里必须有 %s）：10-16 真机就从「7天内再点亮N次必得」
  # 变成「9天内点亮6次必得」，两种都得被测到。
  : >"$W/count"; local v f=${SBX_COUNT_WORD:-7天内再点亮%s次必得}
  for v in "$@"; do
    [ -n "$v" ] && printf "$f\n" "$v" >>"$W/count" || printf '\n' >>"$W/count"
  done
}
reset_env() {
  rm -rf "$W"; mkdir -p "$W"
  printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0"></hierarchy>' >"$W/empty.xml"
  export SBX_SHOT=$SBX/shot.png SBX_EVENTS=$W/events SBX_PUSH=$W/push
  export SBX_COUNT_FILE=$W/count SBX_COUNT_IDX_FILE=$W/idx SBX_XML=$W/empty.xml
  export SBX_TSV_CAND=$W/cand.tsv SBX_TSV_BAND=$W/band.tsv
  export SBX_TSV_PILL1=$W/pill1.tsv SBX_TSV_PILL2=$W/pill2.tsv
  export SBX_PEND_TEXT=
  : >"$SBX_TSV_CAND"; : >"$SBX_TSV_BAND"; : >"$SBX_TSV_PILL1"; : >"$SBX_TSV_PILL2"
  : >"$SBX_EVENTS"; : >"$SBX_PUSH"; : >"$W/count"
  export SBX_OFFLINE=0 SBX_WAKE=Awake SBX_LOCK=0
  export SBX_FPKG=com.xunmeng.pinduoduo
  export SBX_FACT=com.xunmeng.pinduoduo.ui.activity.MainFrameActivity
  PATHP="$SBX/bin:$SBX/farm"
  MK=0
  # 断言开关一律在 reset_env 里清零：每个用例都是先 reset 再设自己那几个，
  # 漏了 unset 也不会把上一个用例的期望带过来
  unset EXPECT_TAPS EXPECT_CLOSE EXPECT_PAUSE EXPECT_TITLE EXPECT_LOG EXPECT_NOLOG \
        EXPECT_BACKS SEED_PAUSE SBX_PEND_MISS SBX_COUNT_WORD SBX_BAND_MISS 2>/dev/null
}

run_case() { # run_case 名字 期望rc 期望lit(-不查) 期望标记(-不查) [额外sed...]
  local name=$1 wrc=$2 wlit=$3 wmark=$4; shift 4
  if [ -n "${ONLY:-}" ] && [ "$ONLY" != "$name" ]; then return 0; fi
  local dir=$SBX/cases/$name
  rm -rf "$dir"; base "$dir"
  [ "$MK" = 1 ] && touch "$dir/runs/.done-$(date +%F)"
  # 预置桌面那个账本文件：里面只有一个天数，脚本读写它，但任何数字都不挡路
  [ -z "${SEED_PAUSE:-}" ] || printf '%s\n' "$SEED_PAUSE" >"$dir/pause"
  while [ $# -gt 0 ]; do sed -i "$1" "$dir/pdd.sh"; shift; done
  local logs rc lit marker taps backs bad=
  logs=$(cd "$dir" && PATH="$PATHP" timeout 240 bash "$dir/pdd.sh" run 2>&1); rc=$?
  lit=$(printf '%s\n' "$logs" | grep -o 'lit=[0-9]*' | head -1 | tr -dc '0-9')
  ls "$dir"/runs/.done-* >/dev/null 2>&1 && marker=yes || marker=no
  local taps; taps=$(grep -c '^tap' "$SBX_EVENTS" 2>/dev/null)
  local backs; backs=$(grep -c 'KEYCODE_BACK' "$SBX_EVENTS" 2>/dev/null)
  # 开局 RESTART_APP 也要 force-stop，所以"成功收尾关应用"只认事件序列的最后两行：
  # 先 am force-stop 再 key KEYCODE_HOME —— 中间任何一步失败都凑不出这个尾巴。
  local closes gotclose=0
  closes=$(tail -2 "$SBX_EVENTS" 2>/dev/null | tr '\n' '|')
  case $closes in
    "am force-stop "*"|key KEYCODE_HOME|") gotclose=1 ;;
  esac
  local pushed; pushed=$(grep -c '^TITLE' "$SBX_PUSH" 2>/dev/null)
  printf '%s\n' "$logs" >"$dir/out.log"
  [ "$rc" = "$wrc" ] || bad="$bad rc=$rc(应$wrc)"
  [ "$wlit" = "-" ] || [ "${lit:-}" = "$wlit" ] || bad="$bad lit=${lit:-无}(应$wlit)"
  [ "$wmark" = "-" ] || [ "$marker" = "$wmark" ] || bad="$bad 标记=$marker(应$wmark)"
  if [ -n "${EXPECT_CLOSE:-}" ]; then
    [ "$gotclose" = "$EXPECT_CLOSE" ] || bad="$bad 收尾关应用=$gotclose(应$EXPECT_CLOSE)"
  fi
  if [ -n "${EXPECT_TAPS:-}" ]; then
    [ "${taps:-0}" = "$EXPECT_TAPS" ] || bad="$bad 点击=${taps:-0}(应$EXPECT_TAPS)"
  fi
  # 兑换账本：查完脚本有没有真的把屏幕上那个 N 写进文件（NONE=文件压根不存在）
  if [ -n "${EXPECT_PAUSE:-}" ]; then
    local pgot; pgot=$(head -1 "$dir/pause" 2>/dev/null || echo NONE)
    [ "${pgot:-NONE}" = "$EXPECT_PAUSE" ] || bad="$bad 倒数=${pgot:-（空）}(应$EXPECT_PAUSE)"
  fi
  if [ -n "${EXPECT_TITLE:-}" ]; then
    grep -q "TITLE$(printf '\t')$EXPECT_TITLE" "$SBX_PUSH" 2>/dev/null \
      || bad="$bad 标题里没有「$EXPECT_TITLE」"
  fi
  # 走的是哪条路只能从日志上看：认到按钮字 vs 一个字都不点，看的是 POP 那行
  if [ -n "${EXPECT_LOG:-}" ]; then
    grep -qF "$EXPECT_LOG" "$dir/out.log" || bad="$bad 日志里没有「$EXPECT_LOG」"
  fi
  # 「关福袋」这一枪：待兑换那轮必须正好按一次 BACK 退出活动页，多按就把 app 也退了
  if [ -n "${EXPECT_BACKS:-}" ]; then
    [ "${backs:-0}" = "$EXPECT_BACKS" ] || bad="$bad BACK=${backs:-0}(应$EXPECT_BACKS)"
  fi
  if [ -n "${EXPECT_NOLOG:-}" ]; then
    grep -qF "$EXPECT_NOLOG" "$dir/out.log" && bad="$bad 日志里不该有「$EXPECT_NOLOG」"
  fi
  if [ -n "$bad" ]; then
    FAILED=$((FAILED + 1))
    printf '%-24s rc=%-3s lit=%-3s 标记=%-3s tap=%-3s BACK=%-2s 推送=%-2s 收尾关=%-2s ✗%s\n' \
      "$name" "$rc" "${lit:-?}" "$marker" "${taps:-0}" "${backs:-0}" "${pushed:-0}" "$gotclose" "$bad"
    grep -E '\[(FAIL|WARN|STEP|CHECK|DONE|POP)\]' "$dir/out.log" | tail -8 | sed 's/^/      /'
  else
    printf '%-24s rc=%-3s lit=%-3s 标记=%-3s tap=%-3s BACK=%-2s 推送=%-2s 收尾关=%-2s ✓\n' \
      "$name" "$rc" "${lit:-?}" "$marker" "${taps:-0}" "${backs:-0}" "${pushed:-0}" "$gotclose"
  fi
  return 0
}

NL=$'\n'
T_SUB="$(row 官方补贴 60 590 130 40)$NL$(row 百亿补贴 60 640 130 40)$NL"
T_BAG="$(row 抽福袋 60 880 110 40)$NL"
# 10-16 晚上真机那一帧：「百亿消费券」卡挪到第二格，同一颗胶囊中心在 (435,524)。
# 老 REGION_bag 的 x 上限 396 会把它当同名噪声拒掉，这条就是钉住"放开到整幅"这个修法。
T_BAG_R="$(row 抽福袋 380 504 110 40)$NL"
T_LIGHT="$(row 立即点亮 430 235 270 110)$NL"
T_DONE="$(row 今日已点亮 430 235 270 110)$NL"
T_EXC="$(row 立即兑换 430 235 270 110)$NL"
T_BROWSE="$(row 滑动浏览当前页面10秒即可点亮 150 440 400 30)$NL"
T_POP="$(row 关闭 500 100 80 40)$NL"
# 10-10 真机读到的奖励浮层：进度行和胶囊都被它盖住，整页只余这两行
T_PRIZE="$(row 恭喜提前锁定限时翻倍券 150 560 420 34)$NL"
# 10-11 真机读到的终态行：7 天跑满后「再点亮N」整行被它顶掉（实测命中中心 296,265）
# 注意 row 的签名是「文本 left top w h」，一句一行：把两句话塞成一个参数会让 left 列变成中文，
# 整份 TSV 解析失败，连 bag 那一行都跟着读不到（10-11 就这么翻过一次）。
T_PEND="$(row 点亮任务已完成 150 250 300 34)$(row 3天后可兑换 460 250 200 34)$NL"
# 10-25/10-26 真机：她把兑换到的券用掉了，活动页顶部那一行整行换成「5折 最高减15元 已使用」，
# 进度行和 pend 那三句一个都不在 —— 两天各 3 枪判"停在轮播另一帧"，rc=5 报「PDD 失败」。
# 这一行的命中中心实测在 (622,268)、分数 3，桩照同一个位置摆。
T_USED="$(row 已使用 560 250 120 35)$NL"
# 胶囊档的坐标在裁片自己的坐标系里：×2 那档要除以 2 再叠 429,235 的原点
P2_LIGHT="$(row 立即点亮 200 100 145 20)$NL"
P1_DONE="$(row 今日已点亮 100 40 72 30)$NL"
# 奖励浮层上那颗主按钮，同一套坐标系（PILL_take 框 0.15,0.553,0.849,0.622 的 ×2 档）
P2_TAKE="$(row 开心收下 200 100 145 20)$NL"

echo "桩沙箱 $(date '+%F %T') 被测=$SRC 行数=$(wc -l <"$SRC") 屏=$SBX_SIZE"
reset_env; MK=1; run_case marker-already-done 0 - -
reset_env; PATHP="$SBX/bin_note:$SBX/farm"
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT"; run_case no-tesseract 78 - no
reset_env; PATHP="$SBX/bin_noadb:$SBX/farm"; run_case no-adb 69 - -
reset_env; SBX_OFFLINE=1; run_case device-offline 2 - no
reset_env; SBX_WAKE=Asleep; SBX_LOCK=1; run_case locked 3 - no
reset_env; SBX_FPKG=com.miHoYo.YYS; SBX_FACT=com.miHoYo.YYS.UnityPlayerActivity
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT"; run_case wrong-foreground 7 - no
reset_env; tsvfile "$W/cand.tsv" "$T_SUB"
  # 认不到字就退 COORD_bag（10-20 删过又恢复，这颗现在是线上配置的一部分）。
  # 这一例钉的是「兜底那一枪真的开了火，而且点错后被 PROVE_KEY=bag 拦下、当场报错」：
  # 只看 rc=5 没牙——把这颗坐标删掉它照样 rc=5，只是少一枪。删掉它这条就红在
  # 「日志里没有 bag 用 coord 点」。
  EXPECT_TAPS=2 EXPECT_LOG="bag 用 coord 点 $(sx 100) $(sy 895)" run_case bag-not-found 5 - no
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_DONE"; countfile 4 4
  run_case already-lit 0 1 yes
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_EXC"; countfile 4 4
  SEED_PAUSE=1
  EXPECT_CLOSE=0 EXPECT_BACKS=0 EXPECT_PAUSE=0 EXPECT_TITLE='PDD 需要你动手' \
  EXPECT_LOG='兑换窗口已到，倒数作废' run_case exchange-needs-human 0 2 no
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_BROWSE"; countfile 4 4 3
  EXPECT_CLOSE=1 EXPECT_LOG="下滑 x=$(sx 540) $(sy 1200)->$(sy 700)" run_case happy-ocr 0 3 yes
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG_R$T_LIGHT$T_BROWSE"; countfile 4 4 3
  EXPECT_CLOSE=1 EXPECT_LOG="bag 用 ocr 点 $(sx 435) $(sy 524)" \
  run_case bag-right-slot 0 3 yes
# 10-18 真机：点亮跳到「消费券」页，那一页整页没有进度卡，原地滚回顶部＋点浮层四枪
# 全空（白耗 99 秒）。滑完直接按 BACK：落到的是**百亿补贴频道页**，也不是活动页，
# 但那一页上「抽福袋」胶囊认得到字，点它回活动页才读到 4→3。
# countfile 依次 = prove-bag / before / after-back / after-reenter。
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_BROWSE"; countfile 4 4 '' 3
  EXPECT_CLOSE=1 EXPECT_BACKS=1 EXPECT_TAPS=4 \
  EXPECT_LOG='进度行 3 次是重进活动页读到的' run_case browse-reenter-venue 0 3 yes
# BACK 那一下就落在带进度卡那一页（10-09 那版任务栈）：不该再多点一枪胶囊。
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_BROWSE"; countfile 4 4 3
  EXPECT_CLOSE=1 EXPECT_BACKS=1 EXPECT_TAPS=3 \
  EXPECT_LOG='进度行 3 次是 BACK 回上一页读到的' run_case browse-back-reads 0 3 yes
# 10-18 真机：横幅「滑动浏览当前页面10秒即可点亮」明明在 y=457，整页 psm11 一个字没吐、
# 整页 psm6 只吐商品行、band 档 psm7 空、band 档 psm11 空 —— 四档全瞎，browse_page 直接返回 1，
# 一下没滑，rc=6。同一张 band 裁片换 psm 6 才读到（conf 89~94）。
# 这条把 browse 的 band psm 列表钉住：cand.tsv 里故意不放横幅那一行，只有 band.tsv 有，
# 并且 7/11 两档回空 —— 少试一档 psm 6，滑动的这一步就不会发生，EXPECT_LOG 立刻对不上。
reset_env; export SBX_BAND_MISS="7 11"
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT"; countfile 4 4 3
  tsvfile "$W/band.tsv" "$(row 浏览当前页面 900 300 300 60)"
  EXPECT_CLOSE=1 EXPECT_LOG='这一屏要滑满' run_case browse-band-psm6 0 3 yes
# 10-16 真机换了措辞：进度行读成「9天内点亮6次必得」，没有「再」字（10:01 和 10:45 两次跑
# 存下的整页帧都一样）。COUNT_TEXT 只认「再点亮」时这一轮三枪全 rc=5；改成 '再点亮|天内点亮'
# 之后必须能走通，并且点完 6 变 5 才算核实过。
reset_env; SBX_COUNT_WORD='9天内点亮%s次必得'
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_BROWSE"; countfile 6 6 5
  EXPECT_CLOSE=1 EXPECT_TAPS=3 EXPECT_PAUSE=0 EXPECT_TITLE='PDD 完成' \
  EXPECT_LOG='进度从 6 次变成 5 次' run_case count-new-wording 0 3 yes
# 浮层盖住了进度行和胶囊：那两行字本身就是点着了的凭据。这一路「开心收下」读不到，
# 10-20 傍晚起退到 COORD_take 那颗量好的中心（(359,752)，10-10 那一帧量的），
# 所以是四枪而不是三枪。日志必须写成「按量好的中心收」而不是「认到」——
# 这一枪是盲的，出问题时得能从日志看出来。
# 浮层是盖在**活动页**上的，所以这一组不放 T_BROWSE：放了就先被滑页那条路的 BACK 带走，
# 测的就不再是原地那一枪（10-18 把 BACK 提到原地判定之前，这里得跟着分清）。
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_PRIZE"
  countfile 4 4 '' '' ''; EXPECT_CLOSE=1 EXPECT_TAPS=4 EXPECT_TITLE='PDD 完成' \
  EXPECT_LOG="按量好的中心收 $(sx 359) $(sy 752)" EXPECT_NOLOG='浮层上认到' \
    run_case prize-take-coord 0 3 yes
# 10-11 量过的那颗按钮：整页 psm 6/11 一个字读不到，只有裁+反色+×2+psm 7 读得清，
# 所以「开心收下」这一路必须走胶囊档。这条和上一条都是四枪、都报 PDD 完成，光数枪分不出
# 是哪条路 —— 所以这里按的是「日志里不许出现按中心那一枪」：胶囊档哪天坏了，它会红。
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_PRIZE"
  tsvfile "$W/pill2.tsv" "$P2_TAKE"
  countfile 4 4 '' '' ''; EXPECT_CLOSE=1 EXPECT_TAPS=4 EXPECT_TITLE='PDD 完成' \
    EXPECT_LOG='浮层上认到「开心收下 ' EXPECT_NOLOG='中心收' \
    run_case prize-take-ocr 0 3 yes
# 10-11 终态：进度行整个没了，屏幕上是「点亮任务已完成…3天后可兑换」
# pend_scan 拿整页 OCR 抄那句原文，桩里用 SBX_PEND_TEXT 喂（必须在 reset_env 之后赋值，
# reset_env 会把它清成空）；脚本先把空格抹掉再按行 grep，最后拼成一句进推送。
reset_env; export SBX_PEND_TEXT=$'点亮任务已完成 恭喜获得限时翻倍券\n3天后可兑换 券已放进口袋'
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_PEND"; countfile '' '' '' '' ''
  EXPECT_TAPS=2 EXPECT_CLOSE=0 EXPECT_BACKS=0 EXPECT_PAUSE=3 EXPECT_TITLE='PDD 已点亮' \
    run_case pend-proof-ok 0 4 yes
# 同一个终态，但只在点完之后才出现：把 cmd_run 里点前那次 pend 检查关掉（缩进定位，只这一处），
# 让流程真的走到 verify_light 的 return 4 —— 不这么干的话前一次检查就把它截了。
reset_env; export SBX_PEND_TEXT=$'点亮任务已完成 3天后可兑换'
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_PEND"; countfile '' '' '' '' ''
  EXPECT_TAPS=3 EXPECT_CLOSE=0 EXPECT_BACKS=0 EXPECT_PAUSE=3 EXPECT_TITLE='PDD 已点亮' \
    run_case pend-verify-4 0 4 yes 's|^        if pend_hit; then$|        if false; then|'
# 屏幕上抄到句子但句子里没有「N天后」：账本里没有能减的数，就一个字都不写
reset_env; export SBX_PEND_TEXT=$'点亮任务已完成 待兑换'
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_PEND"; countfile '' '' '' '' ''
  EXPECT_TAPS=2 EXPECT_CLOSE=0 EXPECT_BACKS=0 EXPECT_PAUSE=NONE EXPECT_TITLE='PDD 已点亮' \
    run_case pend-days-unreadable 0 4 yes
# 「1天后可兑换」：记的是屏幕上那个 1 原值（照抄，不做 N-1）
reset_env; export SBX_PEND_TEXT=$'点亮任务已完成\n1天后可兑换'
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_PEND"; countfile '' '' '' '' ''
  EXPECT_TAPS=2 EXPECT_CLOSE=0 EXPECT_BACKS=0 EXPECT_PAUSE=1 EXPECT_TITLE='PDD 已点亮' \
    run_case pend-days-1 0 4 yes
# 屏幕上的天数抄不到（桩里不给 pend 文本）：账上原来 3 天，往下减一天记成 2
reset_env; export SBX_PEND_TEXT=
  SEED_PAUSE=3
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_PEND"; countfile '' '' '' '' ''
  EXPECT_TAPS=2 EXPECT_CLOSE=0 EXPECT_BACKS=0 EXPECT_PAUSE=2 EXPECT_LOG='账上的 3 天往下减 1' \
    run_case pend-days-roll 0 4 yes
# 屏幕上读到的天数说了算：账本里写着 9，屏幕说 3，最后必须留 3
reset_env; export SBX_PEND_TEXT=$'点亮任务已完成 3天后可兑换'
  SEED_PAUSE=9
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_PEND"; countfile '' '' '' '' ''
  EXPECT_TAPS=2 EXPECT_CLOSE=0 EXPECT_BACKS=0 EXPECT_PAUSE=3 EXPECT_LOG="「3 天后可兑换」，照抄" \
    run_case pend-days-copy 0 4 yes
# 现状那档（psm 6）整页读不出天数，换 PEND_PSM 里的下一档才读到 —— 10-13 真机就是这个样子
# （离线拿存下的 pend 帧量过：psm 6 只 2/4 有天数，psm 11/12 各 4/4）。桩按 --psm 分档回空。
reset_env; export SBX_PEND_TEXT=$'点亮任务已完成 3天后可兑换' SBX_PEND_MISS="6 12"
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_PEND"; countfile '' '' '' '' ''
  EXPECT_TAPS=2 EXPECT_CLOSE=0 EXPECT_BACKS=0 EXPECT_PAUSE=3 EXPECT_TITLE='PDD 已点亮' \
    EXPECT_LOG='天数=3（psm 11 读出的）' \
    run_case pend-days-psm-fallback 0 4 yes
# 10-25/10-26 真机那一屏：进度行读不到、pend 词面也不在，屏幕上只有「已使用」。
# proof_ok 新加的那条救场必须接住它 —— 而且接到之后一个坐标都不许点：
# 桩里那颗「已使用」给的是 (622,268)，COORD_light 是 (598,285)：x 差 622-598=24、y 差 285-268=17，
# 哪天 done 读不到，兜底那一枪就落在这张卡的下方边缘上。
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_USED"; countfile '' '' '' '' ''
  EXPECT_TAPS=2 EXPECT_CLOSE=1 EXPECT_BACKS=0 EXPECT_TITLE='PDD 完成' \
  EXPECT_LOG='这一轮没得可点' EXPECT_NOLOG='light 用 coord' \
  run_case used-terminal 0 1 yes
# 同一屏的第二半：「已使用」这一行只有 band 档换到 psm 6 才读得到（真机 12 帧里 psm 7 全空、
# psm 6 12/12）。cand.tsv 里故意不放这一行，7/11 两档回空 —— OCR_PSM_BAND_done 里少了 6，
# 这一例就会退回 rc=5 那条老路。
reset_env; export SBX_BAND_MISS="7 11"
  tsvfile "$W/cand.tsv" "$T_SUB$T_BAG"; countfile '' '' '' '' ''
  tsvfile "$W/band.tsv" "$(row 已使用 560 250 120 35)"
  EXPECT_TAPS=2 EXPECT_CLOSE=1 EXPECT_BACKS=0 EXPECT_TITLE='PDD 完成' \
  EXPECT_LOG='这一轮没得可点' EXPECT_NOLOG='light 用 coord' \
  run_case used-band-psm6 0 1 yes
# 10-11 的翻车路线：进度行读不到 -> BACK 重试，第二枪只剩固定坐标可退，这一枪被
# RECOVERY_NO_COORD 拦下来。COORD_bag 现在是线上配置（10-20 删过又恢复），这一例不用再
# 注——它和 bag-not-found 钉的是同一条流水的两半：那一条钉"主线开火"，这一条钉"闸门关得住"。
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_LIGHT"; countfile
  EXPECT_TAPS=2 EXPECT_CLOSE=0 \
  EXPECT_LOG='只认出固定坐标' run_case recovery-coord-ban 5 - no
# 坐标兜底一共五颗：subsidy / bag / light / take / dialog。
# 这一例钉"入口和点亮这两颗兜底还点得成"：屏上只认得到胶囊，入口和点亮都走坐标，仍然跑成 lit=3。
reset_env; tsvfile "$W/cand.tsv" "$T_BAG"; countfile 4 4 3
  EXPECT_LOG="light 用 coord 点 $(sx 598) $(sy 285)" run_case happy-coord 0 3 yes
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_BROWSE"
  tsvfile "$W/pill2.tsv" "$P2_LIGHT"; countfile 4 4 3; run_case happy-pill-band 0 3 yes
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_BROWSE"
  tsvfile "$W/pill1.tsv" "$P1_DONE"; countfile 4 4; run_case already-lit-pill 0 1 yes
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_BROWSE"; countfile 4 4 4
  run_case count-unchanged 6 - no
reset_env; tsvfile "$W/cand.tsv" "$T_BAG"; countfile 4 4 '' '' 5 ''; EXPECT_CLOSE=0 \
  EXPECT_LOG="light 用 coord 点 $(sx 598) $(sy 285)" \
  run_case count-unreadable-coord 6 - no
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_POP"; countfile 4 4 '' 3
  run_case popup-rescue 0 3 yes
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT"; countfile
  run_case carousel-wrong-frame 5 - no
reset_env
  X1=$(sx 60) Y1=$(sy 600) X2=$(sx 200) Y2=$(sy 660)
  X3=$(sx 60) Y3=$(sy 880) X4=$(sx 170) Y4=$(sy 920)
  cat >"$W/hier.xml" <<XML
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" content-desc="百亿补贴" bounds="[$X1,$Y1][$X2,$Y2]" />
  <node index="1" text="抽福袋" resource-id="" content-desc="" bounds="[$X3,$Y3][$X4,$Y4]" />
</hierarchy>
XML
  export SBX_XML=$W/hier.xml
  tsvfile "$W/cand.tsv" "$T_LIGHT$T_BROWSE"; countfile 4 4 3
  run_case xml-channel-hit 0 3 yes

# -------------------------------------------- 兑换账本：里面的数字一律不挡路
# 10-11 她改的口径：不再手写暂停令，这个数由脚本自己从屏幕上读，所以任何值都要照常碰手机。
# 正常点亮那一天，账上写着 3 也照跑，跑完清成 0（倒数作废）
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_BROWSE"; countfile 4 4 3
  SEED_PAUSE=3 EXPECT_TAPS=3 EXPECT_CLOSE=1 EXPECT_PAUSE=0 EXPECT_LOG='兑换倒数作废' \
    run_case ledger-normal-zero 0 3 yes
# 账里是垃圾字符：不挡路，跑完写回 0（闸门那套"读不出数字就不跑"已经整个删掉了）
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_BROWSE"; countfile 4 4 3
  SEED_PAUSE=abc EXPECT_TAPS=3 EXPECT_CLOSE=1 EXPECT_PAUSE=0 \
    run_case ledger-garbage-runs 0 3 yes
# 账本文件不存在：正常跑完建一个 0
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_LIGHT$T_BROWSE"; countfile 4 4 3
  EXPECT_TAPS=3 EXPECT_CLOSE=1 EXPECT_PAUSE=0 run_case ledger-no-file 0 3 yes
# 屏幕上读到「今日已点亮」那种日子：也算正常周期，账同样清 0
reset_env; tsvfile "$W/cand.tsv" "$T_SUB$T_BAG$T_DONE"; countfile 4 4
  SEED_PAUSE=2 EXPECT_TAPS=2 EXPECT_PAUSE=0 run_case ledger-already-lit-zero 0 1 yes

echo
echo "失败用例数: $FAILED"
echo SBX_DONE
