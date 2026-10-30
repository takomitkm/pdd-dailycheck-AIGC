#!/usr/bin/env bash
# 负对照：把某一处代码改坏，对应那条用例必须挂红。挂了就说明它真的在钉那段代码，不是白过的。
#
# 前置：先跑过 scripts/run-sandbox.sh（它把 /tmp/pddsandbox/in 铺好），本脚本在那份拷贝上改。
# 每条只跑一个用例（ONLY=），九条各钉一件事。编号只是标签，真跑哪个用例写在第 5 个参数里
# （不给就按编号当用例名）——下面几条标题档跑的就不是自己的编号：
#   browse-reenter-venue  「BACK 落在频道页就点胶囊回活动页」那句判据
#   bag-not-found         COORD_bag 这颗兜底在主线真的会开火（删掉它，日志里就没那一枪）
#   prize-take-coord      COORD_take 那颗中心同上
#   used-terminal         proof_ok 里「读不到进度行但屏幕上写着已使用」那条救场
#   used-band-psm6        OCR_PSM_BAND_done 里那个 6（band 档不换档就读不到这一行）
#   used-title-split      标题分档：读到「已使用」必须报「PDD 已使用」而不是 ✅（跑 used-terminal）
#   lit1-title            标题另一头：lit=1 而屏幕上不是「已使用」必须报 ✅（跑 already-lit）
#   entry-retry-guard     入口那一枪被弹窗吃掉时的「还在首页吗」判据（跑 entry-swallowed-back）
#   focus-fail-closed     焦点行没有斜杠时的两道新闸：awk 退到窗口标签 + 读不到就判失败（跑 shade-slashless-focus）
# 判据的锚点写在下面每条里，改 pdd.sh 那句话时记得同步这里。
set -u
SS=(ssh -4 -o ConnectTimeout=10 deb-h61)
NEG=/tmp/pddsandbox-neg

run_neg() { # $1=编号 $2=sed 表达式 $3=锚点正则 $4=yes(补丁后应还能 grep 到)/no(应 grep 不到) $5=用例名(默认同 $1)
  local nm=$1 expr=$2 pat=$3 want=$4 cs=${5:-$1}
  echo "===== 负对照：$nm（跑用例 $cs）"
  "${SS[@]}" "set -u
[ -d /tmp/pddsandbox/in ] || { echo '没有 /tmp/pddsandbox/in，先跑 scripts/run-sandbox.sh'; exit 1; }
rm -rf $NEG; mkdir -p $NEG
cp -a /tmp/pddsandbox/in $NEG/in
sed -i '$expr' $NEG/in/pdd.sh
if grep -q -- '$pat' $NEG/in/pdd.sh; then got=yes; else got=no; fi
[ \"\$got\" = '$want' ] || { echo 'NEG_PATCH_FAILED：补丁没做成（锚点找不到或还在），负对照不算'; exit 1; }
# 补丁把脚本改出语法错，用例一样会挂红，可那种红钉的不是判据（10-30 第一条就这么假绿过一次：
# sed 替换里的 & 是「整段命中」，那行直接被打废，rc=2 其实是 bash 的语法错退出码）。
bash -n $NEG/in/pdd.sh || { echo 'NEG_PATCH_BROKEN_SYNTAX：补丁改完脚本读不进，这条负对照不算'; exit 1; }
SBX_IN=$NEG/in SBX_ROOT=$NEG/run ONLY=$cs bash $NEG/in/sbx.sh >$NEG/out.txt 2>&1
grep -E '$cs|失败用例数' $NEG/out.txt
# 咬住 = 输出里真有这一条用例的失败行。ONLY 写了个不存在用例名时沙箱一个用例都不跑、
# 直接报「失败用例数: 0」，看着像绿的那一条其实是没测（10-27 就这么漏过一条），所以这道检查留着。
grep -qE '^$cs[[:space:]].*✗' $NEG/out.txt || echo '没咬住：输出里没有用例 $cs 的失败行（用例名打错或它压根没跑）'
"
}

# text_present bag 那句判据恒假 -> 那一枪不再打，EXPECT_LOG 对不上
run_neg browse-reenter-venue 's#text_present bag; then#false; then#' 'false; then' yes
# 删掉兜底那颗坐标 -> 主线少一枪，「日志里没有 bag 用 coord 点」应当报红
run_neg bag-not-found '/^COORD_bag=/d' '^COORD_bag=' no
# 同上，钉 COORD_take
run_neg prize-take-coord '/^COORD_take=/d' '^COORD_take=' no
# proof_ok 那条「已使用」救场换成一个永远配不上的 key -> 三枪判完收手，used-terminal 应当挂在 rc=5
run_neg used-terminal 's|^  if text_present done; then$|  if text_present done_x; then|' 'text_present done_x' yes
# band 档退回只有 psm 7 -> 「已使用」这一行读不到，used-band-psm6 应当挂
run_neg used-band-psm6 's|^OCR_PSM_BAND_done=.*|OCR_PSM_BAND_done=7|' '^OCR_PSM_BAND_done=7$' yes
# 标题分档那一支的字符串改掉 -> 读到的还是「已使用」、lit 还是 1、点枪还是 2，只有标题退回 ✅；
# used-terminal 应当挂在「标题里没有「PDD 已使用」」——这条钉的是"她看得懂的那一行字"也在测试里
run_neg used-title-split 's|title="PDD 已使用"|title="PDD ✅"|' 'title="PDD 已使用"' no used-terminal
# 反过来钉 ✅ 那一半：lit=1 但屏幕上不是「已使用」（桩里是「今日已点亮」）必须报 ✅；
# 把默认标题换成别的字，already-lit 就挂在「标题里没有「PDD ✅」」
run_neg lit1-title 's|local title="PDD ✅"|local title="PDD 完"|' 'local title="PDD ✅"' no already-lit
# 10-30 新增那条判据恒假 -> 弹窗吃掉入口那一枪后不再退、不再补点，直接走到 bag 白找：
# entry-swallowed-back 应当挂在 rc/枪数/BACK 数和「点完还在首页」那句日志上。
# 替换里的 & 是「整段命中」，必须写成 \&\&，否则这行会被撑成垃圾、脚本连读都读不进（上一条就栽过）。
# 「false; then」这份仓库里只可能由这条补丁产生（改前 grep 计数 0），所以 want=yes 能当锚点。
run_neg entry-retry-guard 's#&& is_home_page "\$now"; then#\&\& false; then#' 'false; then' yes entry-swallowed-back

# 这条要同时破两处，是因为 10-30 晚间实测过只破一处各会怎样（两份补丁各跑一遍 ONLY=shade-slashless-focus）：
#   只把空 pkg 放行改回来（保留 awk 的窗口标签退回）→ 用例**照样绿**：pkg 读到 StatusBar ≠ PKG，
#     仍然拒绝，rc=7、0 枪，一条断言都抓不到它。
#   只破 awk 那一半（保留 fail-closed）→ 用例红，但只红在「日志里没有『前台是 StatusBar 而不是』」
#     这一项，rc=7 / 0 枪 / 1 BACK 全对 —— 钉的是措辞，不是"会不会盲点"这个行为。
# 两条一起破 = 回到 10-30 之前的行为，才出现真正的行为差：3 枪、rc=5、BACK=2、日志里没有那句拒绝。
# 两处都用不带引号尾巴的片段替换：awk 那行的行尾是字符串的收引号，sed 表达式里塞不进单引号
# （远端命令整条也在单引号里），所以只换 print lbl; 这一段，把 exit}' 原样留着。
# 锚点用 -z "$pkg"：改前全库 0 命中（旧的 fail-open 已删），只有这条补丁能把它造出来。
run_neg focus-fail-closed 's|print lbl;|print "";|; s|^  \[ "\$pkg" = "\$PKG" \] && return 0$|  [ -z "\$pkg" ] \&\& return 0|' '-z "\$pkg"' yes shade-slashless-focus

echo "NEGCHECK_DONE（上面九条每条都应当是 ✗ / 失败用例数: 1）"
