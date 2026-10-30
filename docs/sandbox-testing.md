# 桩沙箱：怎么跑、断言什么、坑在哪

沙箱的目的只有一个：**不碰手机、不推通知、不碰真账本**，把 `pdd.sh` 的分支矩阵全跑一遍。
它靠 `PATH` 隔离做到这一点——工具农场把 `/usr/bin` 等目录逐个软链，但**排除掉
`adb` / `tesseract` / `curl` / `scrcpy`**，所以被测脚本能看到的这三个命令永远是桩。

## 跑

```sh
bash scripts/run-sandbox.sh                        # 默认 720x1280，全 41 例，约 5 分钟
SBX_SIZE=1440x2560 bash scripts/run-sandbox.sh     # 同一份标定数据换一块屏
ONLY=happy-ocr bash scripts/run-sandbox.sh         # 只跑一例（sbx.sh 直接接受 ONLY）
bash scripts/negative-control.sh                   # 负对照
```

验收口径：末行 `失败用例数: 0`，并且头行打印的 `屏=` 是你指定的那块。

用例数怎么自己数：`grep -c "run_case " sandbox/sbx.sh` 现在给 **42**，其中 1 行是
`run_case() {` 那条函数定义（[sbx.sh:135](../sandbox/sbx.sh#L135)），42-1=**41 例**。
每次加用例都要把 README 和这里两处数字一起改，改漏一次就有一份文档在说过期的数。

**不能并发跑。** 两跑共用 `/tmp/pddsandbox/run` 和 `$SBX_EVENTS`，会撞出一堆假失败。
`scripts/run-sandbox.sh` 开头用 `mkdir /tmp/pddsandbox.lock` 抢锁（mkdir 是原子的），抢不到就停，
`trap` 在退出时 `rmdir`。这里以前写的是"数 `ps` 里的 sbx.sh 进程"，那个口径会把 ssh 自己那条
命令行算进去、而且崩掉的上一跑不留痕 —— 现役脚本用的是锁目录，那段说明一直没跟着改。
哪天换的查不到：仓库里动过 `pddsandbox.lock` 这个字符串的提交只有 `543f0fd`（初始导入），
换锁在那之前。锁没被正常释放时：`ssh deb-h61 rmdir /tmp/pddsandbox.lock`。

## 三个桩各自回什么

| 桩 | 行为 | 由什么控制 |
| --- | --- | --- |
| `bin/adb` | `devices` / `connect` 回在线状态；`input tap|swipe|keyevent` 一律只往 `$SBX_EVENTS` 追加一行；`uiautomator dump` 回成功；`exec-out screencap` 吐出 `$SBX_SHOT`；`exec-out cat` 吐出 `$SBX_XML`；`dumpsys window` 回可控的前台 activity；`wm size` 回 `$SBX_SIZE` | `SBX_OFFLINE` `SBX_WAKE` `SBX_LOCK` `SBX_FPKG` `SBX_FACT` `SBX_SIZE` `SBX_SHOT` `SBX_XML` `SBX_DEV` `SBX_FACT_AFTER_TAP` `SBX_FACT_AFTER_BACK` |
| `bin/tesseract` | 按**输入文件名**路由：`*cand.png` 给整页 TSV，`*band.png` 给 band 档，`*pill-1/2.png` 给胶囊两档，`*count.png` / `*pend.png` 按序号给进度行和天数行 | `tsvfile` / `countfile` 两个 helper 写内容 |
| `bin/curl` | 只把推送正文落到文件，不出网 | `SBX_PUSH` |

点击事件的计数就来自 `$SBX_EVENTS`——这是"到底点了几下、点了什么"的唯一证据源，
不是日志文本。

**前台 activity 不是一块常量板**（10-30 加的）。桩 `dumpsys window` 现在按 `$SBX_EVENTS` 里出现过
什么事件来回报焦点：出现过 `^tap ` 就用 `SBX_FACT_AFTER_TAP`，出现过 `key KEYCODE_BACK` 就用
`SBX_FACT_AFTER_BACK`（两者都为空串 = 那一档不生效，退回 `SBX_FACT`）。默认值在 `reset_env` 里
照真机的形状给：点完入口 = `NewPageActivity`，BACK 不改焦点 —— 因为 10-23…10-27 五次成功跑
subsidy 点完前台都是 `NewPageActivity`，只有 10-30 那次被弹窗吃掉才留在首页。默认写成"点了也
还在首页"的话，入口吞枪那道守卫会在旧用例里误触发；把形状反过来，守卫就永远测不到。
要演"点了没走"，用例自己覆盖成 `SBX_FACT_AFTER_TAP=`。

## 断言的是行为，不是文本

每个用例给 `run_case 名称 期望退出码 期望lit 期望标记`，再加可选的 `EXPECT_*`：

- 退出码和 `lit`（本轮判定出来的状态，见 [states-and-exit-codes.md](states-and-exit-codes.md)）
- 今天标记写没写、账本写成什么数
- `$SBX_EVENTS` 里 tap / swipe / keyevent 各有几条
- app 关没关
- **推送标题**（`EXPECT_TITLE`，现役 22 处断言）：桩 `bin/curl` 把 `title=` 原样记进 `$SBX_PUSH`，
  断言按 `TITLE\t<整串标题>` 匹配。10-27 起七处 `notify` 的标题各有一到多条用例钉着，见
  [states-and-exit-codes.md](states-and-exit-codes.md)「推送标题」那一节
- 日志里**必须出现某一行具体几何**，例如：
  - `happy-ocr` → `下滑 x=540 1200->700`
  - `count-unreadable-coord` → `light 用 coord 点 598 285`
  - `bag-right-slot` → `bag 用 ocr 点 435 524`

位置钉现在一共 5 条（`bag` 的坐标枪与 ocr 枪、`light` 的两条坐标枪、「按量好的中心收」那颗），
最早三条是 10-18 去像素化时新加的，作用是：**光看 rc 和 lit 是测不出坐标准不准的**，
必须把"点了哪个像素"钉进断言。

10-26 那两条（`used-terminal` / `used-band-psm6`）反过来用 `EXPECT_NOLOG`：断言日志里
**不许**出现 `light 用 coord 点`。它们考的不是"点得准不准"，而是"认不到字时有没有开始盲点"——
桩里那颗「已使用」放在 `(622,268)`，`COORD_light` 是 `(598,285)`，x 差 `622-598=24`、
y 差 `285-268=17`，所以读不到那行字的后果就是往那张卡下方边缘打一枪。

10-30 的 `entry-swallowed-stuck` 是第三种用法，钉的是守卫**真的就地收手**：
`EXPECT_NOLOG="bag 用 coord 点 100 895"` 断言 bag 那一枪根本没开，配 `EXPECT_TAPS=3`
（subsidy 三枪，没有第四枪给 bag）、`EXPECT_BACKS=2`（守卫退两次）、标题 `PDD ❌ 退出码 4`。
姊妹用例 `entry-swallowed-back` 演的是退掉之后走通：4 枪 2 BACK 退 0。

这两条的红法有实测对照：负对照第八条把守卫的判据改成恒假，back 那条从 4 枪 2 BACK 掉回
3 枪 1 BACK、并且少了「点完还在首页」那行日志（`失败用例数: 1`，实测在上面那张表下面）。
同一副补丁下 stuck 那条会怎么走没测——负对照每次只跑自己那一例。

## SBX_SIZE：换分辨率怎么测

用例里的几何一律按 720x1280 那套写死，跑别的尺寸时由 `sx()` / `sy()` 折算过去：

```sh
RSX=$(awk -v w="$SBX_W" 'BEGIN{printf "%.6f", w/720}')
```

桩截图也按 `SBX_SIZE` 现生成，桩 `adb` 报的点空间也用它。于是"同一份标定数据换一块屏"
必须给出**完全相同**的判定（rc / lit / 点几下 / BACK 几下），且期望日志里的像素跟着翻。
选 1440x2560 是因为它是整 2 倍，折算全是整数，比对没有取舍歧义。

## 五条硬自检（`sbx.sh` 的 `base()`）

改沙箱之前先看这五条，它们全是 `exit 1` 级的：

```sh
grep -q 'PUSH_URL=http://stub.push/send' "$dir/pdd.sh"   # 没换掉 → 41 例往真实 ServerChan 推 41 条
grep -q "^PUSH_URL_FILE=$dir/push.url\$" "$dir/pdd.sh"   # 没换掉 → PUSH_URL 为空时去读桌面上那个真端点
grep -q "^PAUSE_FILE=$dir/pause$"        "$dir/pdd.sh"   # 没换掉 → 读写真实兑换账本
grep -q 'SWIPE_COUNT=2 '                 "$dir/pdd.sh"   # sed 没锚上 → 按真实时长跑，一遍十几分钟
grep -qE 'sct...|push\.ft07\.com|...'    "$SRC"          # 被测脚本本体里还有真凭据形态 → 停（仓库是公开的）
```

第一条 sed 的锚点很脆（靠 `SWIPE_DUR=300 SWIPE_COUNT=20 SWIPE_WAIT=1` 这一串字面匹配）。
10-18 把 `SWIPE_*` 改成比例后那串一度变了，锚点差点断掉——断了的后果是 41 条真推送和
真实账本被改。所以自检不是洁癖，是门禁。**动了配置区那一片文字，先确认锚点还在。**

第五条和第二条是 10-18 转公开之后加的。端点从"写在 `pdd.sh` 里"改成"运行时读
`$PUSH_URL_FILE` 第一行"以后，只换 `PUSH_URL=` 那一行不够：脚本会在 `PUSH_URL` 为空时
转头去读 `$HOME/Desktop/pdd-push.url`，也就是她主机上那个真端点。所以两条都得钉住。

## 负对照

`scripts/negative-control.sh` 每次把源码里的一处改坏，然后只跑对应那一条用例（`ONLY=`），
改完立刻按锚点 `grep` 确认改动真的落上了 —— 锚点找不到或还在就 `NEG_PATCH_FAILED` 退出，
否则"没挂"会被误读成"测试没用"。锚点过了之后还有一道 `bash -n`：补丁把脚本改出语法错，
用例一样挂红，可那种红钉的不是判据（这道门是 10-30 现学的，见本节末）。现在八条，
最后一次在现役 `82d9f9ef` 那 1930 行上跑（10-30 19:05 落盘），每条都挂：

| 改坏什么 | 哪条用例该挂 | 挂在哪 |
| --- | --- | --- |
| `text_present bag; then` 改成恒假 | `browse-reenter-venue` | 点击=3(应 4)、日志里没有「进度行 3 次是重进活动页读到的」 |
| 删掉 `COORD_bag` | `bag-not-found` | 点击=1(应 2)、日志里没有「bag 用 coord 点 100 895」 |
| 删掉 `COORD_take` | `prize-take-coord` | 点击=3(应 4)、日志里没有「按量好的中心收 359 752」 |
| `if text_present done; then` 里的 key 改成不存在的 `done_x` | `used-terminal` | rc=5(应 0)、lit=0(应 1)、标记=no(应 yes)、点击=3(应 2)、BACK=1(应 0)、收尾关应用=0(应 1)、标题里没有「PDD 已使用」、日志里没有「这一轮没得可点」 |
| `OCR_PSM_BAND_done="7 6"` 改回 `7` | `used-band-psm6` | 同上，一条不差 |
| `title="PDD 已使用"` 换成 `✅` | `used-terminal` | **只**挂在「标题里没有「PDD 已使用」」——rc、lit、标记、点枪、BACK、关 app 全对 |
| `local title="PDD ✅"` 换成别的字 | `already-lit` | 只挂在「标题里没有「PDD ✅」」 |
| 入口守卫 `[ "$key" = "$TOP_RETRY_KEY" ] && is_home_page "$now"` 的后半改成恒假 | `entry-swallowed-back` | 点击=3(应 4)、BACK=1(应 2)、日志里没有「点完还在首页，多半被弹窗吃了」；rc/lit/标记/标题/关 app **全不跟着变** |

**最后两条钉的是标题，不是判定**，所以它们的红法只许有一项：别的维度一旦跟着变，说明标题那两行
参与了判定，那是事故。这两条也是这条表里唯一"改坏之后行为几乎没变"的，留着的原因是她看的就是这一行字。

10-27 现学的一条工具教训（写在这儿因为它会伪装成绿灯）：`run_neg` 原先把**编号**同时当 `ONLY=`
的用例名用。新加的那条编号叫 `used-title-split`、要跑的用例却是 `used-terminal`，于是沙箱一个用例
都没跑就报「失败用例数: 0」——负对照"过了"，实际什么都没测。现在编号和用例名是两个参数
（第 5 个不填才沿用编号），并且强制要求沙箱输出里真有那条用例的 ✗ 行，否则打印「没咬住」。
反证做过：拿一个不存在的用例名走这道检查，它报「没咬住」。

10-30 又现学一条同罪的：第八条的 sed 替换段我写成 `&& false; then`，**没转义 `&`** ——
sed 的替换里 `&` 是"整段命中"，那一行被撑成一串重复文本，脚本连读都读不进，`bash` 的语法错
退出码正好也是 2，桩里没人能把它和"设备掉线"分开。用例照样挂红、红法照样"像钉住了守卫"
（rc=2、tap=0、日志一行没有），可它咬的是补丁把文件改坏了，不是判据。所以 `run_neg` 现在在锚点
检查之后补一道 `bash -n $NEG/in/pdd.sh`，不过就 `NEG_PATCH_BROKEN_SYNTAX` 退出，这种红不算数。
替换段改成 `\&\& false; then` 之后，第八条的红法才是表里写的那三项。

表里第 4、5 行是 10-26 加 `已使用` 终态那条路时补的，两条都要留，因为它们依赖的不是同一处：
`used-band-psm6` 同时吃两处改动（band 档要 psm 6 才出字 + `proof_ok` 要认 done），
`used-terminal` 的字从 `cand.tsv` 给、整页那档先命中，按用例定义看跟 band 的 psm 无关。
**这半句是从桩的路由推出来的，没有实测** —— 负对照每次只跑自己那一例（`ONLY=`），
把 band 的 psm 改回去再跑 `used-terminal` 这一枪没打过。
实测到的是：两条控制各自把自己那条用例打红，且两次的红法**字面完全相同**：
rc=5、lit=0、不写标记、多点一枪（兜底退到 `COORD_light (598,285)`，见上面那条 `EXPECT_NOLOG`）、
多一次 BACK、不关 app。只看 rc 会漏掉"它开始乱点了"这件事，所以上面那一列是把六个维度全列出来的。

`bag-not-found` / `prize-take-coord` 是 10-20 那天现学的教训：**恢复/删除一颗坐标兜底，
只断言退出码是没牙的** ——
`bag-not-found` 有坐标（打错一枪再报错）和没坐标（直接报错）都是 `rc=5`，
必须断言"日志里有没有那一枪"和"点了几下"才能把两种行为分开。10-26 这两条同罪：
`used-terminal` 改坏之后 rc 也会变，但它还会多点一枪（盲点 `COORD_light`）、多一次 BACK、
不写标记、不关 app —— 只看 rc 会漏掉"它开始乱点了"这件事。

另一路负对照是**旧字节对照**：10-18 拿 10-18 11:34 那版还是像素的 `pdd.sh`（md5 `91c857e9`）
在 1440x2560 上跑，结果恰好挂 2 条坐标/滑动的钉、OCR 命中那条照绿——
这既证明了新测试有牙，也证明了哪些东西本来就跟分辨率无关。
