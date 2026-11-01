# 桩沙箱：怎么跑、断言什么、坑在哪

沙箱的目的只有一个：**不碰手机、不推通知、不碰真账本**，把 `pdd.sh` 的分支矩阵全跑一遍。
它靠 `PATH` 隔离做到这一点——工具农场把 `/usr/bin` 等目录逐个软链，但**排除掉
`adb` / `tesseract` / `curl` / `scrcpy`**（[sbx.sh:41](../sandbox/sbx.sh#L41)），所以被测脚本能看到的
这三个命令永远是桩；`scrcpy` 也在排除名单里但没有桩，因为 `pdd.sh` 根本不调它（全仓库只有那一行排除名单提到它）。

## 跑

```sh
bash scripts/run-sandbox.sh                        # 默认 720x1280，全 47 例，约 5 分钟
SBX_SIZE=1440x2560 bash scripts/run-sandbox.sh     # 同一份标定数据换一块屏
ONLY=happy-ocr bash scripts/run-sandbox.sh         # 只跑一例（sbx.sh 直接接受 ONLY）
bash scripts/negative-control.sh                   # 负对照
```

验收口径：末行 `失败用例数: 0`，并且头行打印的 `屏=` 是你指定的那块。

用例数怎么自己数：`grep -c "run_case " sandbox/sbx.sh` 现在给 **48**，其中 1 行是
`run_case() {` 那条函数定义（[sbx.sh:143](../sandbox/sbx.sh#L143)），48-1=**47 例**。
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
| `bin/adb` | `devices` / `connect` 回在线状态；`input tap|swipe|keyevent` 一律只往 `$SBX_EVENTS` 追加一行；`uiautomator dump` 回成功；`exec-out screencap` 吐出 `$SBX_SHOT`；`exec-out cat` 吐出 `$SBX_XML`；`dumpsys window` 回可控的前台 activity；`wm size` 回 `$SBX_SIZE` | `SBX_OFFLINE` `SBX_WAKE` `SBX_LOCK` `SBX_FPKG` `SBX_FACT` `SBX_SIZE` `SBX_SHOT` `SBX_XML` `SBX_DEV` `SBX_FACT_AFTER_TAP` `SBX_FACT_AFTER_BACK` `SBX_FOCUS_RAW` |
| `bin/tesseract` | 按**输入文件名**路由：`*cand.png` 给整页 TSV，`*band.png` 给 band 档，`*pill-1/2.png` 给胶囊两档，`*count.png` / `*pend.png` 按序号给进度行和天数行 | `tsvfile` / `countfile` 两个 helper 写内容 |
| `bin/curl` | 只把推送正文落到文件，不出网。11-02 起它还得演 `notify()` 用的那三个开关：`-o <文件>` 写正文、`--stderr <文件>` 写"错误"（桩里写空，跟真 curl 成功时一样）、`-w <格式>` 按真 curl 的口径把 `%{http_code}`→`200`、`%{exitcode}`→`0`、`%{time_total}`→`0.050000` 打出来（md5 `2e00e208`） | `SBX_PUSH` |

桩 `curl` 那三个开关不是装饰：`notify()` 现在把「http 码 / curl 退出码 / 耗时」当成败依据的一部分，
**桩少演一个，第 47 例 `push-metrics-in-log` 就红** —— 那种红是桩的问题，不是判据的问题，
别照着它去改 `pdd.sh`。反过来，`-w` 那串真被摘掉时红的也只有那一行日志（第十一条负对照实测）。

点击事件的计数就来自 `$SBX_EVENTS`——这是"到底点了几下、点了什么"的唯一证据源，
不是日志文本。

**前台 activity 不是一块常量板**（10-30 加的）。桩 `dumpsys window` 现在按 `$SBX_EVENTS` 里出现过
什么事件来回报焦点：出现过 `^tap ` 就用 `SBX_FACT_AFTER_TAP`，出现过 `key KEYCODE_BACK` 就用
`SBX_FACT_AFTER_BACK`（两者都为空串 = 那一档不生效，退回 `SBX_FACT`）。默认值在 `reset_env` 里
照真机的形状给：点完入口 = `NewPageActivity`，BACK 不改焦点 —— 因为 10-23…10-27 五次成功跑
subsidy 点完前台都是 `NewPageActivity`，只有 10-30 那次被弹窗吃掉才留在首页。默认写成"点了也
还在首页"的话，入口吞枪那道守卫会在旧用例里误触发；把形状反过来，守卫就永远测不到。
要演"点了没走"，用例自己覆盖成 `SBX_FACT_AFTER_TAP=`。

**焦点行也能整行照抄**（10-30 晚加的）。`SBX_FOCUS_RAW` 非空时桩 `dumpsys window` 不再套
`Window{id u0 包名/活动名}` 那个形状，直接打印给的那一行。加它是因为真机 19:20 那一帧焦点行是
`Window{c485e35 u0 StatusBar}`（通知栏盖着桌面）—— **没有斜杠**，而 `foreground_pkg` 和
`focused_act` 两个 awk 都是"取第一个带斜杠的字段"，读到的是空串。只有 `SBX_FPKG`/`SBX_FACT`
这一对旋钮时造不出这种形状，所以那个缺陷在当时的 41 例里演不出来。`reset_env` 把它清成空串，
旧用例一条不受影响。

## 断言的是行为，不是文本

每个用例给 `run_case 名称 期望退出码 期望lit 期望标记`，再加可选的 `EXPECT_*`：

- 退出码和 `lit`（本轮判定出来的状态，见 [states-and-exit-codes.md](states-and-exit-codes.md)）
- 今天标记写没写、账本写成什么数
- `$SBX_EVENTS` 里 tap / swipe / keyevent 各有几条
- app 关没关
- **推送标题**（`EXPECT_TITLE`，现役 23 处断言）：桩 `bin/curl` 把 `title=` 原样记进 `$SBX_PUSH`，
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

## 配置文件那四条（11-01 加）

11-01 把 OCR 那套值从 `pdd.sh` 里搬到 `pdd-ocr.conf` 之后，沙箱多了一个维度要钉：
**"调用照配置引用"这件事本身**。版面判定那 42 例一条没动，新加的四例（42+4=46）不测版面，测装载。
11-01 晚又加了第 47 例 `push-metrics-in-log`（推送那三个指标真的从 `curl` 手里拿到了；
随 11-02 那一版一起交），
所以现在是 42+4+1=**47 例**；这一例不属于"配置文件那四条"，单开在下一节。

`run_case` 多了一个可选环境变量 `SEED_CONF`：非空时把它原样写成用例目录里的 `ocr.conf`
（[sbx.sh:153](../sandbox/sbx.sh#L153)），`base()` 那条 `OCR_CONF_FILE=` 的 sed 正好把它指过去。
**不给 = 没有配置文件**，所以其余 43 例（47-4）跑的一律是内建默认那一路 —— 这也是配置化之后 replay
对照实验必须分两路跑的原因（见 [../scripts/ab-replay.sh](../scripts/ab-replay.sh)）。

| 用例 | 桩给什么 | 期望 | 钉的是哪句话 |
| --- | --- | --- | --- |
| `conf-band-psm6` | `SBX_BAND_MISS="7 11"`（band 档只有 psm 6 出字）+ `SEED_CONF='OCR_PSM_BAND_browse=7 6'`，再加一条把内建默认削成 `=7` 的 sed | rc=0 lit=3 标记=yes tap=3 收尾关=1，日志有「这一屏要滑满」 | 配置真被读 → 阶梯里有 6 → 横幅认到 → 走滑满那条路。**第十条负对照把装载那一步整个摘掉，红的只有这一行日志**：rc=0 / lit=3 / 标记=yes / 收尾关=1 全照旧，因为 `lit=3` 是 `countfile` 给的进度读数，不靠这条横幅（11-01 04:22 那轮第十条复测，红的仍然只有这一行日志） |
| `conf-unknown-key-stops` | `SEED_CONF` 里塞一行 `DEVICE=192.168.1.9:5555` | rc=78，日志有「不在名单里」，标记=no | 名单之外的键不许"看见了但没读"。`DEVICE` 是 `pdd.sh` 配置区里真实存在的变量名，照前缀放行很容易顺手放过 —— 她改了配置、跑的却还是老值，这种静默比不写更坏 |
| `conf-bad-value-stops` | `SEED_CONF='BAND_SCALE=0'` | rc=78，日志原样印出被拒的那行 `BAND_SCALE=0` | 名单里但值不成形也要停。这个数同时是 band 裁片坐标回算的除数，写 0 不会报错、只会把命中点全算飞 |
| `conf-calibration-key-stops` | `SEED_CONF='PILL_light=0.5,0.1,1,0.3'` | rc=78，「不在名单里」 | 逐键列名单 vs 按前缀列名单的差别就在这条上：`PILL_light` 长得像 `PILL_*`，但它是**标定框**不是可调参数。放它进来的话，配置文件就能改写标定数据，而那条路径上一道校验都没有 |

后三例都停在 **78**，走的是同一个出口：装载阶段当场拒、不派发任何 adb。实测三例的桩事件流水
全是 `tap=0 BACK=0 推送=0`、标记=no —— 断言里那几个 `标记=no` 钉的就是"停在碰手机之前"。
`conf-band-psm6` 那一例反过来：它绿的时候是 rc=0 的正常一轮，配置没被读也照样 rc=0，
所以它只能靠那一行日志把两条路分开。这一例写用例时我按"band 全空就会 rc=6"推过一遍，
第十条负对照实测下来那个推断不成立（进度读数把 lit 判成 3、整轮照走），上面那一格已经改成实测的红法。

## 推送诊断那一例（11-01 晚加，第 47 例）

`push-metrics-in-log` 断的是三件事一起成立：标题 `PDD ✅`、日志里有整串
`已推送: PDD ✅（http=200 耗时=0.050000s）`、日志里**不出现**「推送失败」。
`200` 和 `0.050000` 这两个数是桩 `curl` 按 `-w` 的格式吐出来的（见上面桩表那一行），
所以这一例钉的是"`-w` 那串真的传给了 curl、`-o` 那个文件真的有人读"，不是"推送能成"。

它为什么只可能红在日志：推送成不成从来不改退出码，所以 `rc=0 / lit=3 / 标记=yes` 三个断言照旧，
`EXPECT_NOLOG='推送失败'` 是把"降级到 WARN 分支"也算红。配套负对照见下面第十一条。

背景是 11-01 10:05:18 那条 `[WARN] 推送失败: ` 详情为空 —— 冒号后面一个字都没有，三个数一个都没落，
归不了因（README「已知残留」第 12 条）。**这一例就是那种"日志空白"的反面**：只要指标是从 curl 手里
拿到的，成功行也必须带数，下次再出现"整点前后卡一下"就有数可比。

## SBX_SIZE：换分辨率怎么测

用例里的几何一律按 720x1280 那套写死，跑别的尺寸时由 `sx()` / `sy()` 折算过去：

```sh
RSX=$(awk -v w="$SBX_W" 'BEGIN{printf "%.6f", w/720}')
```

桩截图也按 `SBX_SIZE` 现生成，桩 `adb` 报的点空间也用它。于是"同一份标定数据换一块屏"
必须给出**完全相同**的判定（rc / lit / 点几下 / BACK 几下），且期望日志里的像素跟着翻。
选 1440x2560 是因为它是整 2 倍，折算全是整数，比对没有取舍歧义。

## 六条硬自检（`sbx.sh` 的 `base()`）

改沙箱之前先看这六条，它们全是 `exit 1` 级的：

```sh
grep -q 'PUSH_URL=http://stub.push/send' "$dir/pdd.sh"   # 没换掉 → 47 例往真实 ServerChan 推 47 条
grep -q "^PUSH_URL_FILE=$dir/push.url\$" "$dir/pdd.sh"   # 没换掉 → PUSH_URL 为空时去读桌面上那个真端点
grep -q "^PAUSE_FILE=$dir/pause$"        "$dir/pdd.sh"   # 没换掉 → 读写真实兑换账本
grep -q "^OCR_CONF_FILE=$dir/ocr.conf$"  "$dir/pdd.sh"   # 没换掉 → 集体读桌面上那份真配置（11-01 加）
grep -q 'SWIPE_COUNT=2 '                 "$dir/pdd.sh"   # sed 没锚上 → 按真实时长跑，一遍十几分钟
grep -qE 'sct...|push\.ft07\.com|...'    "$SRC"          # 被测脚本本体里还有真凭据形态 → 停（仓库是公开的）
```

第一条 sed 的锚点很脆（靠 `SWIPE_DUR=300 SWIPE_COUNT=20 SWIPE_WAIT=1` 这一串字面匹配）。
10-18 把 `SWIPE_*` 改成比例后那串一度变了，锚点差点断掉——断了的后果是 47 条真推送和
真实账本被改。所以自检不是洁癖，是门禁。**动了配置区那一片文字，先确认锚点还在。**

第六条和第二条是 10-18 转公开之后加的。端点从"写在 `pdd.sh` 里"改成"运行时读
`$PUSH_URL_FILE` 第一行"以后，只换 `PUSH_URL=` 那一行不够：脚本会在 `PUSH_URL` 为空时
转头去读 `$HOME/Desktop/pdd-push.url`，也就是她主机上那个真端点。所以两条都得钉住。

第四条是 11-01 配置化当天加的，罪状和第二条同形：OCR 参数外置以后，`base()` 上面那串
改**内建默认**的 sed 会被桌面上的 `$HOME/Desktop/pdd-ocr.conf` 整体盖掉（配置优先级高于内建默认）。
不重定向 `OCR_CONF_FILE=` 的话，47 例跑的仍是"桌面上那份配置的绿"，而不是这份字节的绿 ——
用例照样全绿，判据却是别人家的值。这条锚点同样是行首 `^OCR_CONF_FILE=`，改配置区那一片文字时一起验。

## 负对照

`scripts/negative-control.sh` 每次把源码里的一处改坏，然后只跑对应那一条用例（`ONLY=`），
改完立刻按锚点 `grep` 确认改动真的落上了 —— 锚点找不到或还在就 `NEG_PATCH_FAILED` 退出，
否则"没挂"会被误读成"测试没用"。锚点过了之后还有一道 `bash -n`：补丁把脚本改出语法错，
用例一样挂红，可那种红钉的不是判据（这道门是 10-30 现学的，见本节末）。现在十一条，
**最后一次十一条逐条跑完是 11-01 21:00:05 起那一轮，测的就是现役 `8ee4382f` 那 2073 行**：自检行印
「桩沙箱 2026-11-01 21:00:05 被测=/tmp/pddsandbox-neg/in/pdd.sh 行数=2073」，源目录那份
`/tmp/pddsandbox/in/pdd.sh`（铺于 20:47，11-02 复查 md5 仍是 `8ee4382fab7ab6f520eb2dd4bde7a886`，
与 01:59:34 部署到桌面的那一串相同）每条复制一份去 `sed`；十一条每条都是 `✗` + `失败用例数: 1`，
末行 `NEGCHECK_DONE`。上一条「十条跑完」的记录留在 11-01：04:22:13 第十条落盘，
1440x2560 那轮自检行是「2026-11-01 04:10:50 …行数=2063」，源 05:36 复查 md5
`cc376aa348c43b2f2474cde2526f8338`——与 04:22:53 部署用的 `/tmp/pdd-deploy-cc376aa3.sh` 同一串。

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
| 焦点闸门两处**一起**改坏：awk 的窗口标签退回换成 `print ""`，加上「读到空串就当可以点」 | `shade-slashless-focus` | rc=5(应 7)、点击=3(应 0)、BACK=2(应 1)、标题里没有「PDD ❌ 退出码 7」、日志里没有「前台是 StatusBar 而不是」 |
| `load_ocr_conf \|\| {` 改成 `true \|\| {`（装载这一步整个摘掉，值退回内建默认） | `conf-band-psm6` | **只**挂在「日志里没有『这一屏要滑满』」——rc=0 / lit=3 / 标记=yes / 点击=3 / 收尾关=1 全对 |
| `-w "%{http_code} %{exitcode} %{time_total}"` 换成 `negctl-blank`（桩 curl 收到的 `-w` 里没了那两个字段） | `push-metrics-in-log` | **只**挂在「日志里没有『已推送: PDD ✅（http=200 耗时=0.050000s）』」——rc=0 / lit=3 / 标记=yes / 点击=3 / BACK=1 / 收尾关=1 全对（11-01 21:00 那轮实测） |

**第 6、7 两行钉的是标题，不是判定**，所以它们的红法只许有一项：别的维度一旦跟着变，说明标题那两行
参与了判定，那是事故。这两条加上末行那条配置装载，是这条表里"改坏之后判定行为几乎没变"的三行，
留着的原因分别是：她看的就是推送标题那一行字；以及配置文件到底有没有被读，只有那一条分辨得出。

第九条是 10-30 晚间那条焦点缺陷的牙，**必须一次破两处**，两处各只破一半的行为是实测过的
（各跑一遍 `ONLY=shade-slashless-focus`，桩和源码都是现役那份）：

- 只把「读到空串就放行」加回来（保留 awk 的窗口标签退回）→ 用例**全绿**：pkg 读到 `StatusBar`
  而 ≠ `$PKG`，闸门照样拒绝，rc=7 / 0 枪 / 1 BACK，一条断言都抓不到。
- 只破 awk 那一半（保留 fail-closed）→ 用例红，但**只红在**「日志里没有『前台是 StatusBar 而不是』」
  这一项，rc=7 / 0 枪 / 1 BACK 全对 —— 那种红钉的是措辞，不是"会不会盲点"这个行为。

两条一起破才回到 10-30 之前的样子：3 枪、rc=5、多一次 BACK、拒绝那行字整个消失。

第十条是 11-01 配置化那天加的，破的是调用侧：把装载这一步 `load_ocr_conf || {` 换成 `true || {`，
配置文件里的值就一个都不生效、全体退回内建默认。锚点是行首那句调用，函数改名会 `NEG_PATCH_FAILED`。
它的红法和 6、7 两行同形 —— **只有一项**「日志里没有『这一屏要滑满』」，rc / lit / 标记 / 枪数 / 关 app
全照旧（上面表末行）。这一条留着是因为它是那 47 例里**唯一**能分辨"配置里的值到底有没有生效"的：
其余 43 例（47-4）压根没给配置文件，走的就是内建默认，装载步骤在不在它们看不出差别；另外 3 例给了
配置，但断的是"停在 78、不派发 adb"，值有没有被取走它们不管。
所以这一例的牙必须落在日志钉上，这也是 `base()` 那第六条自检（`OCR_CONF_FILE=` 重定向）之外
唯一的运行时抓手 —— 只断言 rc 的话，这一条会是个白过的绿。

第十一条（`push-metrics`，11-01 晚和第 47 例一起写的）破的是取数侧：把 `-w` 那串里的两个字段抹掉。
锚点选的是 `negctl-blank` 这种整段替换后的残留串，不是短串 —— 上一版想用 `x y` 当锚点，主机上
`grep -c "x y" /tmp/pdd-new.sh` 一数 = 10 处，那种锚点证明不了补丁落在哪。红法与 6、7、10 三行同形：
**只有一项**「日志里没有『已推送: PDD ✅（http=200 耗时=0.050000s）』」，六个维度全对 ——
推送成从来不改退出码，所以这一例的牙也只能落在日志钉上。它和第 47 例配成一对：
第 47 例钉"成功行也带数"，第十一条钉"数没拿到时第 47 例必须红"。
抹掉之后那一行实际长成什么样，是 21:00:15 从那轮的日志里读出来的（不是推的）：
`已推送: PDD ✅（http=200 耗时=?s）` —— `%{http_code}` 那半截没动所以 200 还在，耗时取不到字段落成 `?`
（日志 `/tmp/pddsandbox-neg/run/cases/push-metrics-in-log/runs/2026-11-01/210005/run.log`，
`negctl-blank` 现在还在 `/tmp/pddsandbox-neg/in/pdd.sh:1479` 那行上）。
**根因仍未归因**：11-01 10:05:18 那条 `[WARN] 推送失败: ` 到底是端点慢、DNS、还是那一刻主机断网，
这一版只是让下次能分清，没加重试、没改判据（README「已知残留」第 12 条）。

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
