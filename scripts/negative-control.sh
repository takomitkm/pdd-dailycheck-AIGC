#!/usr/bin/env bash
# 负对照：把某一处代码改坏，对应那条用例必须挂红。挂了就说明它真的在钉那段代码，不是白过的。
#
# 前置：先跑过 scripts/run-sandbox.sh（它把 /tmp/pddsandbox/in 铺好），本脚本在那份拷贝上改。
# 每条只跑一个用例（ONLY=），五条各钉一件事：
#   browse-reenter-venue  「BACK 落在频道页就点胶囊回活动页」那句判据
#   bag-not-found         COORD_bag 这颗兜底在主线真的会开火（删掉它，日志里就没那一枪）
#   prize-take-coord      COORD_take 那颗中心同上
#   used-terminal         proof_ok 里「读不到进度行但屏幕上写着已使用」那条救场
#   used-band-psm6        OCR_PSM_BAND_done 里那个 6（band 档不换档就读不到这一行）
# 判据的锚点写在下面每条里，改 pdd.sh 那句话时记得同步这里。
set -u
SS=(ssh -4 -o ConnectTimeout=10 deb-h61)
NEG=/tmp/pddsandbox-neg

run_neg() { # $1=用例名 $2=sed 表达式 $3=锚点正则 $4=yes(补丁后应还能 grep 到) / no(应 grep 不到)
  local nm=$1 expr=$2 pat=$3 want=$4
  echo "===== 负对照：$nm"
  "${SS[@]}" "set -u
[ -d /tmp/pddsandbox/in ] || { echo '没有 /tmp/pddsandbox/in，先跑 scripts/run-sandbox.sh'; exit 1; }
rm -rf $NEG; mkdir -p $NEG
cp -a /tmp/pddsandbox/in $NEG/in
sed -i '$expr' $NEG/in/pdd.sh
if grep -q '$pat' $NEG/in/pdd.sh; then got=yes; else got=no; fi
[ \"\$got\" = '$want' ] || { echo 'NEG_PATCH_FAILED：补丁没做成（锚点找不到或还在），负对照不算'; exit 1; }
SBX_IN=$NEG/in SBX_ROOT=$NEG/run ONLY=$nm bash $NEG/in/sbx.sh 2>&1 | grep -E '$nm|失败用例数'"
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

echo "NEGCHECK_DONE（上面五条每条都应当是 ✗ / 失败用例数: 1）"
