#!/usr/bin/env bash
# pdd.sh -- 每天自动跑拼多多的「百亿补贴 -> 抽福袋 -> 立即点亮 + 下滑浏览」，走无线 adb。
#
# 用法:
#   pdd.sh run           完整流程；今天已经完成过就直接成功退出
#   pdd.sh run force     忽略「今天已完成」标记，强制再跑一遍
#   pdd.sh probe         只抓界面：dump + 截图 + 打印可直接粘贴的 COORD_* 行
#   pdd.sh find <key>    解析一个目标但不点
#   pdd.sh point <x> <y> 裸坐标点一下
#   pdd.sh shot          存一张截图并打印路径
#   pdd.sh status        设备 / 依赖 / 标记 / 证据目录概览
#   pdd.sh replay <证据目录>  拿存下来的证据离线重跑判定，不碰手机（改版后先筛配置再上机器）
#
# ~/Desktop/pdd-pause 现在只是兑换账本（脚本自己写的，只有一个数字）：里面记几天都不会跳天，
# 每天 10:00 照常碰手机。真要整天不跑只能动定时器：systemctl --user stop pdd.timer
#
# 目标定位顺序：uiautomator XML -> 稀疏文字 OCR(psm 11) -> 整页文字 OCR(psm 6) -> 固定坐标。
# 点亮那颗胶囊只有整页模式认得出，两种模式都得跑。ALIAS 留空表示这个目标是无字 artwork，
# 直接用 COORD。匹配用「最长公共字符段」，所以 PDD 改文案只要还有 MIN_OVERLAP 个字对得上
# 就还能点中；命中点是那几个字的外接框中心，不是整行中心。
#
# 点「立即点亮」之前先读那颗胶囊：已使用/已点亮/明日再来 = 今天已经完成，算成功；
# 立即兑换 = 脚本不代点；「点亮任务已完成…3天后可兑换/待兑换」(ALIAS_pend) = 7 天跑完了、
# 奖励在等人工兑换 —— 这两种都不算错误（lit=2/4，退出码 0），各推一条通知，
# app 都不关（NO_CLOSE_LIT）：2 停在能直接接手的那一屏，4 停在刚读到「任务已完成」的那一屏，
# 两种都只发推送、一个按键都不多放。
#
# 退出码：0 成功 / 2 设备连不上 / 3 手机锁屏 / 5 卡在某一步没找到（4 起步，每完成一步 +1）
#         / 6 点完了但进度行那个次数没变小或读不到，当失败，不写今天标记
#         / 7 前台不是拼多多 / 69 没有 adb / 78 配置缺或没有 tesseract。
# 每种情况都会推一条通知，正文里带上最后停在哪个 activity。
#
# 每次运行的证据（截图、XML、run.log、summary.txt）落在 $EVIDENCE_DIR，留 KEEP_DAYS 天。

set -uo pipefail
export PYTHONIOENCODING=utf-8
export LC_ALL=${LC_ALL:-C.UTF-8}

# ---------------------------------------------------------------- 配置区
DEVICE=192.168.1.110:16132          # 手机的无线 adb 地址
PKG=com.xunmeng.pinduoduo
MIN_OVERLAP=3                       # 至少几个字对得上算命中；3=宽松，5=近乎精确

STEPS="subsidy bag light"           # 点击顺序：百亿补贴 -> 抽福袋 -> 立即点亮
# 「关闭/暂不」只有两个字，门槛只能放到 2，所以弹窗标签一律留中文：整页 OCR 的英文垃圾串很容易凑出两个字母的公共段
ALIAS_popup='关闭|跳过广告|暂不|以后再说'
OVERLAP_popup=2
# 弹窗这条线停用：唯一能认出它的词「参与活动」同时也是抽福袋之后那一屏的面包屑。
# 09-27 和 10-07 两次都是 dismiss_dialog 对着自己刚点进去的页面按 BACK，把人退出去，
# 后面 点亮 只能拿坐标瞎点，还报成功。真正的广告浮层走 ALIAS_popup。
# key 留着是为了 pdd.sh find dialog 还能手动扫一眼，标签清空 = 不自动按 BACK。
# 清空同时让 dismiss_dialog 整个停用（见那个函数开头的注释）：标签为空时它绝不碰
# COORD_dialog，因为「没认到弹窗」和「认到弹窗」在只有坐标时是分不开的。
ALIAS_dialog=''
OVERLAP_dialog=4
REGION_dialog=0.05,0.10,0.95,0.90
COORD_dialog=0.85694,0.17344        # 弹窗右上角那个 X，写的是屏幕比例（本机 720x1280 上是 617,222）。
                                    # 只在 ALIAS_dialog 非空、
                                    # 且已经认到弹窗、且 BACK 关不掉时才点；不单独触发。
ALIAS_subsidy='百亿补贴|官方补贴'      # 入口是图片，字未必认得到，认不到就用 COORD
OVERLAP_subsidy=4
ALIAS_bag='抽福袋|去抢购'
FIND_RETRY_bag=12                    # 10-07 实测这个位置是轮播：一帧「抽福袋」、一帧「百亿消费券 100元券待领」，
                                    # 三轮扫过去全是后一帧，得给它更多轮次
FIND_INTERVAL_bag=3
ALIAS_light='立即点亮'              # 认得到就按认到的点，认不到退回 COORD_light
# 10-07 实测的新版式：福袋页上那一枪点完跳到「消费券」页，写着「滑动浏览当前页面10秒即可点亮」，
# 滑够 10 秒才算点亮（进度从再点亮4次变成3次，实测过），再 BACK 会直接回到活动页、跳过福袋页。
ALIAS_browse='浏览当前页面|即可点亮'
OVERLAP_browse=4
REGION_browse=0,0.30,1,0.45
# 10-09 实测修正：原来 6 下 x 400ms、下滑之间还隔 2s，手指真正按在屏幕上的时间
# 只有 2.4s，而横幅要的是 10 秒 —— 进度条压根不动。所以改成近乎连续地滑。
# 10-10 再改两条口径：①按秒表滑，不是按下数 —— 一次 adb input swipe 除了 800ms
# 的按压，还有 0.3-0.5s 的建立连接开销，按下数根本对不上真实经过的时间，秒表才
# 对得上；②单次滑动不超过半屏，滑过头会把进度卡甩出屏幕（10-09 那次就是这么卡的）。
BROWSE_SECONDS=15                   # 滑够的墙上时间(秒)，不是按下次数
BROWSE_DUR=800                      # 单次滑动的按压时长(ms)，这才是真正在计时的部分
BROWSE_WAIT=0                       # 两次滑动之间不留空档
BROWSE_MAX_SWIPES=60                # 秒表失灵时的保险丝，别让它无限滑
BROWSE_PROVE=true                   # 滑完再读一次横幅，看倒计时/文案有没有变
# 10-09 实测：浏览完之后人已经在那张「消费券」页上，只是被滑过头了，进度卡在
# 屏幕上面。而 BACK 会退到「百亿补贴」页，那里的「抽福袋」是一颗被「专属补贴」
# 卡压掉一半的小胶囊，OCR 认不出，而这一路走的是 text_present——它按设计不收坐标兜底
# （认不到字就是认不到，不能拿分数=0 的一枪冒充"读到了"），所以当场 FAIL。
# 10-18 把这两半都推翻了一半：消费券页整页确实没有进度卡（BACK 之前原地读 99 秒全空），
# 而频道页那颗胶囊现在认得到字（(435,524)，10-18 真机两次都从那儿进的活动页）。
# 但这一档还是关着 —— BACK 这一枪挪到 verify_light 里无条件打了（滑完必按），
# 在这里再按一次会变成连退两页。
BROWSE_BACK=false
BROWSE_X=0.75                       # 滑动那一条的 x，屏幕比例（720 宽上是 540）
# 点亮那颗胶囊有三种状态，点之前先读一遍屏幕：
ALIAS_done='已点亮|明日再来|明天再来|已使用'   # 今天已经点过 -> 直接算完成
ALIAS_exchange='立即兑换|去兑换'               # 变成兑换了，脚本不代点，只推送
OVERLAP_done=3 OVERLAP_exchange=3
# 10-10 实测：点亮发放后屏幕上盖的是「恭喜提前锁定限时翻倍券 / …可兑换最高50元券」，
# 它同时挡住进度行和那颗胶囊，于是进度读不到、已点亮也读不到，脚本把成功当失败报了 6。
# 这段文字本身就是发奖凭据，所以只在「进度行读不到」那条路上拿来判成功。
# 10-11 按她的要求去掉「可兑换」：券卡别处也可能出现这两个字，只留浮层独有的两段。
ALIAS_prize='翻倍券|提前锁定'
OVERLAP_prize=3
# 那张浮层上的主按钮「开心收下」。整页 psm 6/11 都读不到它（10-10 那帧实测空），
# 只有裁出按钮 + 反色 + 硬阈值 120 + ×2 + psm 7 一次读全 —— 就是胶囊那一档的做法。
ALIAS_take='开心收下'
OVERLAP_take=3
# 10-11 实测：7 天点亮跑完后，福袋页整行「7天内再点亮N次必得」没有了，换成
# 「点亮任务已完成 …… 3天后可兑换」+「待兑换」。这是正常的等待人工兑换状态，不是版面坏了，
# 所以进度行读不到时先认这几个词：认到就按「要她动手」处理（不点、不报错、不关 app）。
# 词面是拿 pdd.sh replay 对着当天存下的帧筛出来的（OCR 把「兑换」念成「交换/可竞」，
# 所以三段都留了能对满 3 个字的部分）。
ALIAS_pend='任务已完成|天后可兑换|待兑换'
OVERLAP_pend=3
# 认到 pend 这一档之后，还要把屏幕上那整句话抄下来（进推送）并抠出「N天后可兑换」的 N。
# finder 只吐命中的那几个字，不够抄，所以再拿整页 psm 6 复读一遍，按行 grep。
# 词面留三种写法：OCR 会把「兑换」念成「交换/可竞」，多留几个对得上的形状。
PEND_LINE_RE='任务已完成|待兑换|天后可'
PEND_DAYS_RE='[0-9]{1,2}天后'
# 抄这句用哪些整页识别档，按顺序试到读出天数为止。10-16 拿 10-12/10-13 存下的 4 张 pend 帧
# 离线量的（不碰手机）：只有 psm 6 时 2/4 读出天数（另两张整页连「天」都没念出来），
# psm 11 和 12 各自 4/4；psm 4 反而只 1/4（另一张念成「点高任务已完成天可半」，数字丢了）。
# 样本只有 4 张、两天，所以这是 B 级；顺序把现状 6 放前面，读不到才往下试。
PEND_PSM="6 11 12"

# 命中点必须落在的屏幕范围，x1,y1,x2,y2 取 0..1，防止别处的同名文字被点
REGION_popup=0.45,0,1,0.45
REGION_subsidy=0,0.30,0.40,0.80     # 只认图标那一行的左半格：09-22 那行在 y=645，09-25 已经掉到 y=779
# 这颗胶囊跟着活动版式换位置：09-22 在 y=526，09-25 已经掉到 y=890。
# 10-09 实测它是一颗又小又浅的胶囊，压在红���上，而它上面那一整排是「加倍补」
# 轮播 —— 整页 OCR 四次里只认到两次。范围收窄到左半边那一列，正好只留这颗
# 胶囊所在的那张卡，顺带让新加的 band 通道能把上面的噪声裁掉。
# 10-16 晚上收成 0.55 那道闸门把这一枪挡死了：「百亿消费券」那张卡整个挪到了第二格，
# 同一颗「抽福袋」胶囊实测在 (435,524)，x 上限 396 差 39 个点，于是整页 OCR 认到 12 次、
# 拒了 12 次，退化去点 COORD_bag(100,895) —— 那个位置当晚是一整张百事可乐商品卡。
# 早上那一跑它又确实在 (111,894)。同一颗胶囊两个版式各在一侧，横向收窄这条已经站不住了，
# 放开到整幅，只靠 y 上下限把顶部「百亿补贴抽福袋」那条横幅（实测 y≈225）隔在外面。
REGION_bag=0,0.35,1,0.85
REGION_done=0,0.08,1,0.42
REGION_exchange=0,0.08,1,0.42
REGION_light=0,0.08,1,0.42
# 奖励浮层那两行字实测在 y≈569/630（1280 高的屏），落在中段；给到 0.30..0.65 留点余量
REGION_prize=0,0.30,1,0.65
# 「开心收下」整页读不到，得靠 band/胶囊档；REGION_take 是命中点闸门，也是让 band_pass
# 往下走到 pill_pass 的门票（REGION_<key> 是空的时 band_pass 直接 return 1，pill 档根本不会跑）。
REGION_take=0,0.50,1,0.70
# 「开心收下」认不到字时退到配置区那颗 COORD_take（10-10 量到的 (359,752)）。
# 10-11 到 10-20 中午这颗是空的：她当时定的是「读不到就不点」，浮层那两行字本身
# 已经是点着了的凭据，少收一次不影响本轮判成功。10-20 傍晚按「有兜底的都补上」恢复。
# 「点亮任务已完成」那行 10-11 拿 replay 对当天三帧实测：ocr 命中 296,265 / 297,269，分数 5，
# 正好顶在过去「7天内再点亮N次必得」的位置（y≈253）—— 所以进度行消失和这行出现是同一件事。
# 区域和 done/exchange/light 那三档对齐，留上下余量。
REGION_pend=0,0.08,1,0.45
# 点亮那颗胶囊是深底白字，整条 REGION 裁出来反而一个字都读不到。10-10 拿 40 帧真图跑的
# 矩阵（pdd-merge/bench5/）：REGION 档 0/12，只裁这颗胶囊 + 反色 + 硬阈值的档 9/12 全对，
# 剩下 3 帧是屏幕上本来就写着「今日已点亮」的。×1 只认得到「今日已点亮」，×2 才认得到
# 「立即点亮」，同一档盖不住两个状态，所以两档并跑。阈值 120 是在这颗胶囊上扫出来的
# （100 和 160 都会花），换控件要重扫。PILL_exchange 这行还没实测过，只是同一个槽位。
PILL_light=0.597,0.184,1,0.270
PILL_done=$PILL_light
PILL_exchange=$PILL_light
# 「开心收下」那颗按钮的框：10-10 那帧真图上量到 108,708..611,796，换算成比例。
# 10-11 拿这帧真图扫过 8 个档：只有「裁这颗按钮 + 反色 + 阈值 120 + ×2 + psm 7」读出
# 干净的「开心收下」，不反色和阈值 150/180/200 那几档全是乱码。
PILL_take=0.15,0.553,0.849,0.622
# 频道页那颗「抽福袋」：10-17/10-18/10-20 三天的 rc=6 全栽在它身上 —— BACK 从消费券
# 浏览页落回百亿补贴频道页，那颗胶囊一直在屏幕上（约 107,888），但整页 psm6 和 band 档
# 都读不出字，于是 text_present bag 扫满 12 轮认不到，退回固定坐标又被核实路线禁掉。
# 10-20 拿当天 3 帧真图量的：紧框 + 原色彩（不转灰度、不 autocontrast、不反色）psm 7/11/6
# 三档全部读出干净的「抽福袋」；同一框转灰度后只剩「最高20元」，反色+阈值只有 psm6 偶然
# 撞上，band 档那套灰度+autocontrast 一个字都读不出来。同一个框在活动页/首页/消费券页
# 4 帧上零命中，不会把别的面板误认成胶囊。
PILL_bag=0.02,0.64,0.32,0.78
PILL_MODE_bag=color
PILL_TH=120
PILL_SCALES="1 2"

# 下面四颗都写 0..1 的屏幕比例，不写像素：比例乘上当前的点空间就是该点的位置，
# 换分辨率（wm size 改过、或者换一台机）不用重校。括号里是在本机 720x1280 上量到的像素。
# 比例一律给 5 位小数：3 位在 1440 宽的屏上就有 0.7px 的系统偏差，5 位折回去像素一个不差。
COORD_subsidy=0.125,0.46875         # (90,600) ALIAS 为空时即主目标
# 抽福袋这一颗 0.13889,0.69922 = 老版式那一格的 (100,895)。10-20 中午按「认不到就该 FAIL」
# 删过它，傍晚翻完保留的 run.log 数了账又恢复：这一枪一共开火 8 次，4 次点的正是那一格、
# 当场进对页面（10-14 读到终态、10-17 读到 5 次、10-18 10:07 读到 4 次、10-19 读到 3 次），
# 另外 4 次（10-16 三次、10-18 11:00 一次）落在轮播的另一帧上。那 4 次不是没报——日志都是
# 「[FAIL] bag 点完读不到进度行」，PROVE_KEY=bag 拦住了，我 10-20 写的「点错了什么也没报」是错的。
# 它只盖得住 (111,894) 这个版式，(435,524) 那一侧盖不住；核实/恢复那条路照旧禁坐标
# （RECOVERY_NO_COORD），所以这一枪只在主线第一枪开火。
COORD_bag=0.13889,0.69922
COORD_light=0.83056,0.22266         # (598,285)
# 「开心收下」的中心：10-10 那帧粉色胶囊实测 108,708..611,796 → (359,752) 折成比例。
# 10-11 她定「读不到就不点」时删过，10-20 按「还有没有兜底的就补上」恢复。
# 只有 take_prize_overlay 用得到这颗，而它只在屏幕上读到奖励浮层那两行字之后才被调——
# 浮层在场是被别的字证明过的。保留的 11 份 run.log 里这一路一次都没开火，
# 所以这颗中心只有一个来源、没有第二次实测。
COORD_take=0.49861,0.58750          # (359,752)
SCROLL_TOP=2                        # 进页面先把信息流拉回顶部，那一格的相对位置才对得上
TOP_RETRY_KEY=subsidy               # 这一步认不到字时，滑到页面最顶端再认一轮
TOP_SWIPES=4
# 10-30：首页盖着「你有支付补贴未使用」，入口那一枪打在遮罩上、页面没走（10:01:41 点下去，10:01:46 前台还是 HomeActivity），
# 可首页那些字在 XML 里一个都没少 → subsidy 被记成成功 → bag 在首页上跑满 12 轮（10:01:46→10:04:00，134 秒）才退 COORD_bag，
# BACK 之后又 12 轮，10:08:14 才报 5（整轮 10:01:41→10:08:14 = 393 秒）。判据换成"点完还在不在首页"（焦点还是首页就是没走），
# 不去读弹窗上写什么字：改版换词都不影响这一条。BACK 是当天实测退得掉那张弹窗的按键（10:04:21 按，10:04:25 那帧首页已经干净、但仍是首页）。
ENTRY_RETRY=2                       # 入口点完还在首页，最多退几次、再点几次
ENTRY_RETRY_WAIT=3

RESTART_APP=true                    # 每次先 force-stop，避免停在旧页面
LAUNCH_WAIT=8 STEP_WAIT=4 FIND_RETRY=3 FIND_INTERVAL=2 POPUP_MAX=3 POPUP_WAIT=2
# 滑动的三个坐标也是 0..1 比例（本机 720x1280 上分别是 x=540、y 从 1200 到 700）。
# 时长、次数、间隔是毫秒和次数，跟分辨率无关，保持原样。
SWIPE_X=0.75 SWIPE_Y1=0.9375 SWIPE_Y2=0.546875 SWIPE_DUR=300 SWIPE_COUNT=20 SWIPE_WAIT=1
# 拉回顶部那一枪是反着滑（手指从上往下），起终点单独配；原来写死 420/1150 像素。
TOP_SWIPE_Y1=0.328125 TOP_SWIPE_Y2=0.8984375
EVIDENCE_DIR=$HOME/Desktop/pdd-runs
KEEP_DAYS=7
# 兑换账本：桌面上这个文件里只有一个数字，= 屏幕上那句「N天后可兑换」的 N。
# 10-11 起她不再手写这个文件，18:41 那版"收条对不上就跳天"的闸门也一起废了 ——
# 它现在只是账本，任何数字都不挡路，每天照常碰手机。
# 写法：读到屏幕上那个 N 就照抄；那天读不到 N 就把账上的数减 1；跑回正常点亮周期写 0；
# 屏幕换成「立即兑换」(lit=2) 也写 0 —— 倒数已经走完，挂着个 1 天读起来像还有得等。
# 真要整天不跑只能动定时器：systemctl --user stop pdd.timer
PAUSE_FILE=$HOME/Desktop/pdd-pause
# 跑干净了就把拼多多整个关掉：它留在前台会占住任务栈，下次启动可能被带回旧页面
CLOSE_APP_ON_OK=true
# 不关 app 的那两种：2=立即兑换，手机停在屏幕前让她直接接手；
# 4=任务已完成等兑换（10-11 她改的「保持在 app 界面通知我」）——这一轮一个按键都不多放，
# 只发推送。10-16 她把原来补在这里的那次 BACK 去掉了（实测那一下连 activity 都没换），
# 所以"关福袋"现在只剩「不点福袋抽奖」这半句，手机停在哪一屏就维持哪一屏。
NO_CLOSE_LIT="2 4"
OCR_LANG=chi_sim+eng OCR_PSM=11 OCR_MINCONF=40 OCR_PSM_PAGE=6
# 裁切放大那条通道专用：psm 7（单行）优先，psm 11（稀疏）兜底。
# 整页 OCR 会跳过低对比度横条，裁出来放大 3 倍 + autocontrast 就能读到。
OCR_PSM_BAND=7
# 只给 browse 这一个键加 psm 6（整块）。10-18 真机：点亮跳到「消费券」页，横幅
# 「滑动浏览当前页面10秒即可点亮」明明在 y=457，四档全瞎 —— 整页 psm11 一个字没吐、
# 整页 psm6 只吐商品行、band 档 psm7 空、band 档 psm11 空，于是 browse_page 直接返回 1，
# 一下没滑，进度行当然没变，rc=6。同一张 band 裁片改成 psm6：浏览 conf=94 页=93 面=93
# 秒=90 亮=89，全在门槛（40）之上，映射回屏幕是 (228,462)，正落在 REGION_browse 里。
# 不动全局 OCR_PSM_BAND 是因为 pick() 取的是文件顺序第一个 in-region 命中，不是最高分：
# 全局加 6 会让 band 在 light/take 那几颗深底胶囊上提前出命中，把 pill_pass 挤掉
# （10-10 矩阵：light 的 band 档 0/12、胶囊反色档 9/12），这个代价没实测过，不担。
OCR_PSM_BAND_browse="7 6"
# 同一把钥匙开第二把锁：只给 done 这一个键也补 psm 6。10-25/10-26 两天 rc=5 的那一屏
# 顶部写着「5折 最高减15元 已使用」（券已经用掉了，进度行整行没了），band 档现档 psm 7
# 读不出这一行 —— 拿存下的 12 帧离线量：裁 REGION_done + 放大 3 倍，psm 7 全空、psm 6 12/12
# 命中，点恒在 (622,268)，分数 3。线上配置不动的话，这一档在同样 12 帧里只认到 4 帧
# （走的是整页 psm 6 那一档，band 补不上）。理由和 browse 同一条：不动全局 OCR_PSM_BAND，
# 因为 pick() 取文件顺序第一个 in-region 命中，全局加 6 会挤掉 light/take 那两颗深底胶囊的 pill 档。
OCR_PSM_BAND_done="7 6"
ABORT_IF_LOCKED=true                # 锁屏有密码时直接放弃，不瞎点
CHECK_DONE_BEFORE=light             # 点「立即点亮」之前先读一遍屏幕，判断是哪种状态
# 活动页上那行进度提示是能机器核对的证据：09-26 实测「7天内再点亮4次」点完变 3。
# 10-10 起点亮那一枪优先走胶囊反色档（真机读到过 立即 点  亮），只有它也没认到才退坐标；
# 所以打完必须回头比对这两个数字，纯坐标那一枪读不到就一律判失败。
# 10-16 真机换了措辞：连着两轮（10:01 和 10:45 两次跑、各自存下的整页帧）都读成
# 「9天内点亮6次必得」—— 没有「再」字。旧写法只认「再点亮」，于是进度行读不到、
# 被当成停在轮播错帧，连着三枪 rc=5。这里改成两种都认。
# 注意：新那行的 6 到底是"还剩 6 次"还是"总共 6 次"还没测（verify 仍然按变小判成功，
# 万一它反过来往上加，会报 rc=6 并把两个数字都写进推送 —— 那就是第一次实测）。
COUNT_TEXT='再点亮|天内点亮'                # light_count 在这个词后面找数字；写 a|b 也行，grep 会自己加括号
# 抽福袋 那个格子是轮播，点进活动页的唯一凭据就是屏幕上那行进度；点错了帧就 BACK 回去等下一轮
PROVE_KEY=bag
PROVE_MAX=3
# 10-11 那次 rc=5：进度行读不到之后连着 BACK 重试，第三枪是「分数=0 的 COORD_bag」盲点，
# 屏幕上早就换成新版式了，点的根本不是福袋格子。核实/恢复这条路上只认字，
# 认不到就当场收手报错，别再拿固定坐标赌。正常第一枪不受影响。
RECOVERY_NO_COORD=true
# 点亮没核实成功时，具体是哪一种情况会写进推送正文：
# 「进度没变」= 真没点着，「读不到进度行」= 版面又变了或中奖后那行消失了，两种要做的事不一样。
VERIFY_WHY=
PEND_SEEN=                        # 屏幕上读到「任务已完成/待兑换」那一档，本轮没得可点
PEND_LABEL=                       # finder 命中的那几个字
DONE_WORD=                        # 读到 done 那一档时屏幕上那几个字，进推送前压掉 OCR 塞的字间空格；日志仍留原文
PEND_LINE=                        # 整页 OCR 抄下来的那一整句，进推送正文用
PEND_DAYS=                        # 「N天后可兑换」里的 N，读不到就留空，绝不猜
PAUSE_WRITTEN=                    # 这次写进 $PAUSE_FILE 的倒数天数，一个字都没写就留空
IN_RECOVERY=                      # 1 = 正走在核实/恢复那条路上，坐标兜底不许开火
# 跑完往手机上推一条，和 src.service 用的是同一个接口；拿不到端点就一条都不推。
# 端点里带 ServerChan 的 send token，等于凭据，所以不写在本文件里（本仓库是公开的）：
# 从 PUSH_URL_FILE 读第一行；文件不在或读不了 = 没配推送，流程照跑、只是不推。
# 环境变量已经给了 PUSH_URL 的优先用环境变量（沙箱和临时覆盖走这条）。
# 换 token 只动那个文件，不用改脚本，也不会进 git。
PUSH_URL_FILE=${PUSH_URL_FILE:-$HOME/Desktop/pdd-push.url}
PUSH_URL=${PUSH_URL:-}
PUSH_URL_SRC=env
if [ -z "$PUSH_URL" ] && [ -r "$PUSH_URL_FILE" ]; then
  PUSH_URL=$(head -1 "$PUSH_URL_FILE" | tr -d ' \t\r\n')
  [ -n "$PUSH_URL" ] && PUSH_URL_SRC="file:$PUSH_URL_FILE"
fi
# 完成标记：$EVIDENCE_DIR/.done-<日期>。三步点完、或屏幕上读到 ALIAS_done 都会写，
# 当天再跑直接 exit 0，完全不碰手机。「立即兑换」只推送、不写标记，下次还会来看。

# 配置缺了就当场停，别默默把流程跑歪
[ -n "${STEPS// /}" ] || { printf 'STEPS 是空的，不知道要点哪几步\n' >&2; exit 78; }
if [ -z "${OCR_PSM:-}" ] || [ -z "${OCR_PSM_PAGE:-}" ]; then
  printf 'OCR_PSM / OCR_PSM_PAGE 没配\n' >&2; exit 78
fi
# 比例一律 0..1。写成像素（比如 90,600）的话乘完飞出屏幕外，点在 (0,0) 上还不报错，
# 所以在这里验死； REGION_/PILL_ 那两批本来就是比例，由 band_pass/pill_pass 自己处理。
# COORD_ 这一族按前缀现取，不写死名单：10-20 那颗 COORD_bag 删了又恢复、又新挂一颗
# COORD_take，写死的名单两头都要跟着改，漏一遍就有一个名字查不到、或一颗坐标不过闸门。
for _v in $(compgen -v COORD_) BROWSE_X SWIPE_X SWIPE_Y1 SWIPE_Y2 \
          TOP_SWIPE_Y1 TOP_SWIPE_Y2; do
  _val=${!_v:-}
  [ -n "$_val" ] || continue
  awk -v v="$_val" 'BEGIN{
    n = split(v, a, ",")
    if (n < 1 || n > 2) exit 1
    for (i = 1; i <= n; i++)
      if (a[i] !~ /^[0-9]*\.?[0-9]+$/ || a[i]+0 < 0 || a[i]+0 > 1) exit 1
  }' || { printf '%s 要写成 0..1 的屏幕比例，现在是「%s」\n' "$_v" "$_val" >&2; exit 78; }
done

# ---------------------------------------------------------------- 基础设施

LOGFILE=
TMP=$(mktemp -d)
RUN_DIR=$EVIDENCE_DIR/$(date +%F)/$(date +%H%M%S)
trap 'rm -rf "$TMP"' EXIT

log() {
  local line
  line=$(printf '%s [%s] %s' "$(date '+%F %T')" "$1" "${*:2}")
  printf '%s\n' "$line"
  [ -n "$LOGFILE" ] && printf '%s\n' "$line" >>"$LOGFILE"
  return 0
}
have() { command -v "$1" >/dev/null 2>&1; }
adb_dev()   { command adb -s "$DEVICE" "$@"; }
adb_shell() { command adb -s "$DEVICE" shell "$@"; }

# adb 只有真的要碰手机时才需要；replay 是纯离线的（读证据目录，不连设备），
# 别拿它挡路。所以这个检查放在 case 之外做，其余子命令行为和以前完全一样。
case ${1:-run} in
  replay) ;;
  *) have adb || { printf '找不到 adb，不在 PATH 里\n' >&2; exit 69; } ;;
esac

# 内嵌的匹配器：XML / OCR TSV / 节点列表 / PNG 尺寸
finder() {
  python3 - "$@" <<'PY'
import re, struct, sys, xml.etree.ElementTree as ET

FIELDS = ("text", "content-desc", "resource-id")
BOUNDS = re.compile(r"\[\s*(\d+)\s*,\s*(\d+)\s*\]\[\s*(\d+)\s*,\s*(\d+)\s*\]")
# 只留文字和汉字，标点空格全去掉，这样文案中间被塞了换行也还能对上
NOISE = re.compile("[^\\w\\u4e00-\\u9fff\\u3400-\\u4dbf]+")


OX = OY = 0.0


def norm(t):
    return NOISE.sub("", t or "")


def lcs(hay, needle):
    """两段文字共享的最长字符段，返回 (长度, 在 hay 里的起点)。"""
    if not hay or not needle:
        return 0, 0
    best, at, prev = 0, 0, [0] * (len(needle) + 1)
    for i in range(1, len(hay) + 1):
        cur = [0] * (len(needle) + 1)
        for j in range(1, len(needle) + 1):
            if hay[i - 1] == needle[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best, at = cur[j], i - cur[j]
        prev = cur
    return best, at


def overlap(hay, needle):
    return lcs(hay, needle)[0]


def nodes(raw):
    try:
        return [{k: v for k, v in e.attrib.items()} for e in ET.fromstring(raw).iter("node")]
    except Exception:
        pass
    return [dict(re.findall(r'([\w:.-]+)="([^"]*)"', m.group(1)))
            for m in re.finditer(r"<node\b([^>]*?)/?>", raw)]


def score_of(field, value, labels):
    clean, best = norm(value), None
    if not clean:
        return None
    for lb in labels:
        if field == "resource-id":
            sc = len(lb) if lb in value else 0
        else:
            sc = overlap(clean, norm(lb))
        if sc >= MO and (best is None or sc > best[1]):
            best = (lb, sc)
    return best


def emit(x, y, source, value, sc):
    # OX/OY let a pass that OCR'd only a cropped band still report
    # full-screen tap coordinates.
    print(f"{int(x * SX + OX)} {int(y * SY + OY)}\t{' '.join(value.split())[:48]} [{source}]\t{sc}")


def run_xml():
    raw = open(FILE, encoding="utf-8", errors="replace").read()
    hits = []
    for n in nodes(raw):
        box = BOUNDS.findall(n.get("bounds") or "")
        if not box:
            continue
        x1, y1, x2, y2 = map(int, box[0])
        for field in FIELDS:
            got = score_of(field, n.get(field) or "", LABELS)
            if got:
                hits.append((got[1], n.get("clickable") == "true",
                             (x1 + x2) / 2, (y1 + y2) / 2, field, n.get(field)))
                break
    hits.sort(key=lambda h: (-h[0], not h[1]))
    for sc, _, x, y, field, value in hits:
        emit(x, y, field, value or "", sc)
    return 1 if not hits else 0


def run_tsv():
    # psm 11 会把汉字拆成一个字一行，psm 6 一整行一个词，两种都得先按行合并
    lines, order = {}, []
    with open(FILE, encoding="utf-8", errors="replace") as fh:
        fh.readline()
        for row in fh:
            c = row.rstrip("\n").split("\t")
            if len(c) < 12 or c[0] != "5":
                continue
            text = c[11].strip()
            if text in ("", "-"):
                continue
            key = (c[2], c[3], c[4])
            if key not in lines:
                lines[key] = {"raw": [], "ch": [], "l": 1 << 30, "u": 1 << 30,
                              "r": 0, "d": 0, "c": []}
                order.append(key)
            e = lines[key]
            e["raw"].append(text)
            left, top = int(c[6]), int(c[7])
            box = (left, top, left + int(c[8]), top + int(c[9]))
            for nch in norm(text):
                e["ch"].append((nch, box))
            e["l"] = min(e["l"], box[0])
            e["u"] = min(e["u"], box[1])
            e["r"] = max(e["r"], box[2])
            e["d"] = max(e["d"], box[3])
            e["c"].append(float(c[10] or 0))
    hits = []
    for key in order:
        e = lines[key]
        if max(e["c"]) < CONF:
            continue
        value = " ".join(e["raw"])
        text = "".join(nch for nch, _ in e["ch"])
        best = None
        for lb in LABELS:
            sc, at = lcs(text, norm(lb))
            if sc >= MO and (best is None or sc > best[1]):
                best = (lb, sc, at)
        if not best:
            continue
        sc, at = best[1], best[2]
        # 命中哪几个字就往哪几个字上点，别用整行中心（psm 6 一行横跨大半屏）
        span = [b for i, (_, b) in enumerate(e["ch"]) if at <= i < at + sc]
        if not span:
            span = [(e["l"], e["u"], e["r"], e["d"])]
        l = min(b[0] for b in span); t = min(b[1] for b in span)
        r = max(b[2] for b in span); d = max(b[3] for b in span)
        hits.append((sc, (l + r) / 2, (t + d) / 2, value))
    hits.sort(key=lambda h: -h[0])
    for sc, x, y, value in hits:
        emit(x, y, "ocr", value, sc)
    return 1 if not hits else 0


def run_nodes(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    rows = []
    for n in nodes(raw):
        lb = (n.get("text") or n.get("content-desc") or "").strip()
        box = BOUNDS.findall(n.get("bounds") or "")
        if not lb or not box:
            continue
        x1, y1, x2, y2 = map(int, box[0])
        rows.append((y1 + y2, x1, (x1 + x2) // 2, (y1 + y2) // 2,
                     (n.get("clickable") or "false")[:1], " ".join(lb.split())[:40]))
    for row in sorted(rows):
        print(f"{row[2]}\t{row[3]}\t{row[4]}\t{row[5]}")
    return 0


def main():
    global MO, LABELS, FILE, SX, SY, CONF, OX, OY
    a, CONF, SX, SY, OX, OY = sys.argv[1:], 40.0, 1.0, 1.0, 0.0, 0.0
    while a and a[0].startswith("--"):
        flag = a.pop(0)
        if flag == "--min-conf":
            CONF = float(a.pop(0))
        elif flag == "--scale":
            SX, SY = float(a.pop(0)), float(a.pop(0))
        elif flag == "--offset":
            OX, OY = float(a.pop(0)), float(a.pop(0))
    mode = a[0] if a else ""
    if mode == "size":
        d = open(a[1], "rb").read(24)
        print(struct.unpack(">II", d[16:24])[0], struct.unpack(">II", d[16:24])[1])
        return 0
    if mode == "nodes":
        return run_nodes(a[1])
    if len(a) < 4:
        print("usage: finder [size f.png|nodes f.xml|xml|tsv f <min-overlap> <label>...]",
              file=sys.stderr)
        return 2
    FILE, MO, LABELS = a[1], int(a[2]), a[3:]
    return run_xml() if mode == "xml" else run_tsv() if mode == "tsv" else 2


sys.exit(main())
PY
}

# ---------------------------------------------------------------- 环境与抓取

device_online() {
  command adb devices 2>/dev/null | grep -q "^${DEVICE}[[:space:]]*device\$"
}

ensure_device() {
  command adb start-server >/dev/null 2>&1
  device_online && return 0
  log WARN "$DEVICE 没连上，正在重连"
  local i
  # timeout 是必需的：adb connect 对死掉的设备会自己挂很久，不加就顶到 15min 上限
  for i in 1 2 3 4; do
    timeout 15 adb connect "$DEVICE" >/dev/null 2>&1
    sleep 2
    device_online && return 0
  done
  return 1
}

read_resolution() {
  local out x y
  out=$(adb_shell wm size 2>/dev/null | tr -d '\r')
  x=$(printf '%s\n' "$out" | sed -n 's/.*[Oo]verride size: *\([0-9]*\)x\([0-9]*\).*/\1/p')
  y=$(printf '%s\n' "$out" | sed -n 's/.*[Oo]verride size: *\([0-9]*\)x\([0-9]*\).*/\2/p')
  if [ -z "$x" ]; then
    x=$(printf '%s\n' "$out" | sed -n 's/.*[Pp]hysical size: *\([0-9]*\)x\([0-9]*\).*/\1/p')
    y=$(printf '%s\n' "$out" | sed -n 's/.*[Pp]hysical size: *\([0-9]*\)x\([0-9]*\).*/\2/p')
  fi
  TAP_W=${x:-720}; TAP_H=${y:-1280}
}

screen_state() {
  adb_shell dumpsys power 2>/dev/null | tr -d '\r' \
    | sed -n 's/.*mWakefulness=\([A-Za-z]*\).*/\1/p' | head -1
}

keyguard_up() {
  adb_shell dumpsys window 2>/dev/null | tr -d '\r' \
    | grep -qiE 'mShowingLockscreen=true|mKeyguardShowing=true|mDreamingLockscreen=true'
}

foreground_pkg() { # 此刻真正占据屏幕的包名
  adb_shell dumpsys window 2>/dev/null | tr -d '\r' \
    | awk '/mCurrentFocus/ {for (i=1; i<=NF; i++) if ($i ~ /\//) {split($i, a, "/"); print a[1]; exit}}'
}

require_pdd() { # $1 = 即将点击的步骤名；不是拼多多在前台就绝不点
  local pkg
  pkg=$(foreground_pkg)
  if [ -z "$pkg" ]; then
    log WARN "读不到当前焦点窗口，继续"
    return 0
  fi
  [ "$pkg" = "$PKG" ] && return 0
  log FAIL "$1: 前台是 $pkg 而不是 $PKG，点下去没有意义"
  grab_shot "$RUN_DIR/lost-$1.png" 2>/dev/null
  return 1
}

wake_screen() {
  [ "$(screen_state)" = Awake ] || adb_shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
  sleep 1
  adb_shell wm dismiss-keyguard >/dev/null 2>&1
  sleep 1
  keyguard_up || return 0
  log WARN "锁屏还在，无法操作"
  [ "$ABORT_IF_LOCKED" = true ] && return 1
  return 0
}

ui_dump() { # $1 = 保存路径
  local i
  for i in 1 2 3; do
    if adb_shell uiautomator dump /sdcard/pdd_dump.xml >/dev/null 2>&1 \
       && adb_dev exec-out cat /sdcard/pdd_dump.xml >"$1" 2>/dev/null \
       && [ -s "$1" ] && grep -q '<hierarchy' "$1"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

grab_shot() { # $1 = 保存路径
  adb_dev exec-out screencap -p >"$1" 2>/dev/null && [ -s "$1" ]
}

# ------------------------------------------------------------------ 找目标

labels_of() { # $1 = key -> 每行一个字面标签
  local v="ALIAS_$1"
  local spec=${!v:-}
  [ -n "$spec" ] || return 1
  printf '%s\n' "$spec" | tr '|' '\n' | sed '/^[[:space:]]*$/d'
}

frac_x() { awk -v f="$1" -v W="${TAP_W:-0}" 'BEGIN{printf "%d", f*W+0.5}'; }
frac_y() { awk -v f="$1" -v H="${TAP_H:-0}" 'BEGIN{printf "%d", f*H+0.5}'; }

frac_xy() { # 「fx,fy」(0..1) -> 点空间「x y」；点空间还不知道时返回 1，不吐 0 0
  [ "${TAP_W:-0}" -gt 0 ] 2>/dev/null && [ "${TAP_H:-0}" -gt 0 ] 2>/dev/null || return 1
  printf '%d %d' "$(frac_x "${1%,*}")" "$(frac_y "${1#*,}")"
}

xy_frac() { # 点空间「x y」-> 「fx,fy」，probe 拿它打印换分辨率也不用重校的 COORD_ 行
  local c=${1/ /,}
  [ "${TAP_W:-0}" -gt 0 ] 2>/dev/null && [ "${TAP_H:-0}" -gt 0 ] 2>/dev/null || return 1
  awk -v c="$c" -v W="$TAP_W" -v H="$TAP_H" 'BEGIN{
    split(c, a, ","); printf "%.5f,%.5f", a[1]/W, a[2]/H
  }'
}

in_region() { # $1 = key, $2 = "x y"
  local v="REGION_$1"
  local spec=${!v:-}
  [ -n "$spec" ] || return 0
  awk -v spec="$spec" -v xy="$2" -v W="$TAP_W" -v H="$TAP_H" 'BEGIN{
    split(spec, r, ","); split(xy, p, " ");
    exit !((p[1]+0) >= r[1]*W && (p[1]+0) <= r[3]*W && (p[2]+0) >= r[2]*H && (p[2]+0) <= r[4]*H)
  }'
}

png_scale() { # 截图分辨率 -> 点空间坐标的缩放，填进 SCALE_ARGS
  local dims d w h
  SCALE_ARGS=()
  dims=$(finder size "$TMP/cand.png") || return 1
  d=($dims); w=${d[0]:-0}; h=${d[1]:-0}
  [ "$w" -gt 0 ] 2>/dev/null || return 1
  SCALE_ARGS=(--scale "$(awk -v a="$TAP_W" -v b="$w" 'BEGIN{printf "%.5f", a/b}')" \
                       "$(awk -v a="$TAP_H" -v b="$h" 'BEGIN{printf "%.5f", a/b}')")
}

pick() { # $1 = key, stdin = 命中列表 -> PICK_XY / PICK_LABEL / PICK_SCORE
  local key=$1 xy value score
  PICK_XY= PICK_LABEL= PICK_SCORE=0
  while IFS=$'\t' read -r xy value score; do
    [ -n "$xy" ] || continue
    if in_region "$key" "$xy"; then
      PICK_XY=$xy PICK_LABEL=$value PICK_SCORE=$score
      return 0
    fi
    log WARN "$key: '$value' 在 $xy，落在 REGION_$key 之外" >&2
  done
  return 1
}

find_target() { # $1 = key -> "方式<TAB>x y<TAB>命中文本<TAB>分数"，每轮都留证据
  local key=$1 attempt ovv ov xml tsv l coord psm rv iv retry xy
  local av="ALIAS_$key" cv="COORD_$key"
  if [ -z "${!av:-}" ]; then
    coord=${!cv:-}
    [ -n "$coord" ] || { log WARN "ALIAS_$key 是空的，COORD_$key 也没配" >&2; return 1; }
    xy=$(frac_xy "$coord") || { log WARN "COORD_$key 是比例，但点空间还不知道，没法换算" >&2; return 1; }
    printf 'coord\t%s\t固定比例\t0\n' "$xy"
    return 0
  fi
  ovv="OVERLAP_$key"; ov=${!ovv:-$MIN_OVERLAP}
  # 轮播位上的目标要多扫几轮：FIND_RETRY_<key> 单独给，别的键仍用全局值
  rv="FIND_RETRY_$key"
  retry=${!rv:-$FIND_RETRY}
  mkdir -p "$RUN_DIR"
  # 证据文件名带上这一枪的秒数：text_present 和活动页重试都会用同一个 key 再扫一遍，
  # 不带后缀的话后一次会把前一次覆盖掉，出问题时手上就只剩"点完 BACK 之后"的图
  local stamp; stamp=$(date +%H%M%S)
  local -a labels=()
  while IFS= read -r l; do labels+=("$l"); done < <(labels_of "$key")
  [ ${#labels[@]} -gt 0 ] || return 1
  for attempt in $(seq 1 "$retry"); do
    xml=""
    local -a passes=()
    if ui_dump "$TMP/cand.xml"; then
      xml=$TMP/cand.xml
      cp -f "$xml" "$RUN_DIR/$stamp-$key-$attempt.xml" 2>/dev/null
    fi
    if have tesseract && [ -n "$OCR_LANG" ] && grab_shot "$TMP/cand.png"; then
      cp -f "$TMP/cand.png" "$RUN_DIR/$stamp-$key-$attempt.png" 2>/dev/null
      png_scale
      # 稀疏文字(psm 11)先试，读不到再用整页文字(psm 6)：点亮那颗胶囊只有 psm 6 认得出
      for psm in $OCR_PSM $OCR_PSM_PAGE; do
        tesseract "$TMP/cand.png" stdout -l "$OCR_LANG" --psm "$psm" tsv \
          >"$TMP/ocr-$psm.tsv" 2>/dev/null && [ -s "$TMP/ocr-$psm.tsv" ] && passes+=("$TMP/ocr-$psm.tsv")
      done
    fi
    if [ -n "$xml" ] \
       && finder xml "$xml" "$ov" "${labels[@]}" >"$TMP/hits.txt" 2>/dev/null \
       && pick "$key" <"$TMP/hits.txt"; then
      printf 'xml\t%s\t%s\t%s\n' "$PICK_XY" "$PICK_LABEL" "$PICK_SCORE"; return 0
    fi
    for tsv in "${passes[@]}"; do
      if finder "${SCALE_ARGS[@]}" --min-conf "$OCR_MINCONF" tsv "$tsv" "$ov" \
           "${labels[@]}" >"$TMP/hits.txt" 2>/dev/null \
         && pick "$key" <"$TMP/hits.txt"; then
        printf 'ocr\t%s\t%s\t%s\n' "$PICK_XY" "$PICK_LABEL" "$PICK_SCORE"; return 0
      fi
    done
    if [ -f "$TMP/cand.png" ] && have tesseract && [ -n "$OCR_LANG" ]; then
      if band_pass "$key" "$TMP/cand.png" && pick "$key" <"$TMP/band-hits.txt"; then
        printf 'band\t%s\t%s\t%s\n' "$PICK_XY" "$PICK_LABEL" "$PICK_SCORE"; return 0
      fi
    fi
    iv="FIND_INTERVAL_$key"
    [ "$attempt" -lt "$retry" ] && sleep "${!iv:-$FIND_INTERVAL}"
  done
  coord=${!cv:-}
  if [ -n "$coord" ]; then
    xy=$(frac_xy "$coord") || return 1
    printf 'coord\t%s\t配置兜底\t0\n' "$xy"
    return 0
  fi
  return 1
}


# 整页 OCR 有时会直接跳过一条低对比度的横条。实测「滑动浏览当前页面10秒即可点亮」
# 就是浅粉底上的粉红字：整页 psm6 在 y380 和 y590 之间整段输出为空，
# 但把 REGION_browse 那一条裁出来放大 3 倍，psm7 一次就读全了。
# 所以对每个配了 REGION_<key> 的目标，补一条「只裁这一条再 OCR」的通道。
band_pass() { # $1 = key, $2 = 截图 -> finder 结果写 $TMP/band-hits.txt
  # NOTE: must be two statements. `local a=$1 b="X_$a"` expands $a during word
  # expansion, i.e. before `local` has run, and `set -u` then kills the script.
  local key=$1 png=$2
  local r="REGION_$key" spec r1 r2 r3 r4 x0 y0 cw ch
  local -a band_passes=() labels=()
  local l psm tsv bsx bsy boxx boyy xy ovv ov geo bstamp
  local bpk="OCR_PSM_BAND_$key" bp
  bp=${!bpk:-$OCR_PSM_BAND}
  # NOTE: not $stamp -- that is find_target's local; under `set -u` a
  # cross-function reference aborts the pass right after a successful hit.
  bstamp=$(date +%H%M%S)
  spec=${!r:-}
  [ -n "$spec" ] || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c 'import PIL' >/dev/null 2>&1 || return 1
  IFS=, read -r r1 r2 r3 r4 <<<"$spec"
  geo=$(BAND_PNG="$png" BAND_SPEC="$spec" python3 - <<'GEOM'
from PIL import Image
import os
im = Image.open(os.environ["BAND_PNG"])
W, H = im.size
x1, y1, x2, y2 = [float(v) for v in os.environ["BAND_SPEC"].split(",")]
pad_x, pad_y = 0.02, 0.015
x0 = max(0, int((x1 - pad_x) * W))
x2 = min(W, int((x2 + pad_x) * W))
y0 = max(0, int((y1 - pad_y) * H))
y2 = min(H, int((y2 + pad_y) * H))
print(x0, y0, x2 - x0, y2 - y0, W, H)
GEOM
) || return 1
  read -r x0 y0 cw ch iw ih <<<"$geo"
  [ "${cw:-0}" -gt 8 ] 2>/dev/null || return 1
  [ "${ch:-0}" -gt 8 ] 2>/dev/null || return 1
  for psm in $bp $OCR_PSM; do
    BAND_PNG="$png" BAND_OUT="$TMP/band.png" BAND_BOX="$x0 $y0 $cw $ch" python3 - <<'CROP'
from PIL import Image, ImageOps
import os
im = Image.open(os.environ["BAND_PNG"])
x, y, w, h = (int(v) for v in os.environ["BAND_BOX"].split())
im = im.crop((x, y, x + w, y + h)).convert("L")
im = ImageOps.autocontrast(im, cutoff=1)
im.resize((im.width * 3, im.height * 3), Image.LANCZOS).save(os.environ["BAND_OUT"])
CROP
    tesseract "$TMP/band.png" stdout -l "$OCR_LANG" --psm "$psm" tsv \
      >"$TMP/band-$psm.tsv" 2>/dev/null \
      && [ -s "$TMP/band-$psm.tsv" ] && band_passes+=("$TMP/band-$psm.tsv")
  done
  [ ${#band_passes[@]} -gt 0 ] || return 1
  # 缩放按「整图」尺寸算，不是裁片尺寸：裁片里第 k 像素在屏幕上的位置是
  # x0 + k * (TAP_W / 整图宽)。用裁片宽高会把裁片拉回全屏，命中点全部飞到
  # REGION 外面去，pick() 会把它们全丢掉（这个坑踩过一次）。
  # /3 是因为裁片放大过 3 倍，tsv 坐标是放大后的。
  bsx=$(awk -v a="$TAP_W" -v b="$iw" 'BEGIN{printf "%.5f", a/b/3}')
  bsy=$(awk -v a="$TAP_H" -v b="$ih" 'BEGIN{printf "%.5f", a/b/3}')
  boxx=$(awk -v a="$x0" -v b="$iw" -v w="$TAP_W" 'BEGIN{printf "%.1f", a/b*w}')
  boyy=$(awk -v a="$y0" -v b="$ih" -v h="$TAP_H" 'BEGIN{printf "%.1f", a/b*h}')
  local av="ALIAS_$key"
  [ -n "${!av:-}" ] || return 1
  while IFS= read -r l; do labels+=("$l"); done < <(labels_of "$key")
  [ ${#labels[@]} -gt 0 ] || return 1
  ovv="OVERLAP_$key"; ov=${!ovv:-$MIN_OVERLAP}
  : >"$TMP/band-hits.txt"
  for tsv in "${band_passes[@]}"; do
    finder --scale "$bsx" "$bsy" --offset "$boxx" "$boyy" \
      --min-conf "$OCR_MINCONF" tsv "$tsv" "$ov" "${labels[@]}" \
      >>"$TMP/band-hits.txt" 2>/dev/null
  done
  # 整条 REGION 没认到，才试胶囊档。顺序不能反：反色会把 subsidy/browse 那种浅底
  # 深色字整个打花（10-10 矩阵：subsidy 现档 6/6、反色档 0/6；browse 现档 3/5、反色 2/5）。
  # 这里不能提前 return —— 胶囊档的触发条件正是「band 一条都没认到」。
  if [ ! -s "$TMP/band-hits.txt" ]; then
    pill_pass "$key" "$png" >>"$TMP/band-hits.txt" 2>/dev/null
  fi
  [ -s "$TMP/band-hits.txt" ] || return 1
  # 命中点必须仍落在 REGION_<key> 里（裁片比 REGION 宽一点，免得切掉半个字）
  while IFS=$'\t' read -r xy _ _; do
    [ -n "$xy" ] || continue
    if in_region "$key" "$xy"; then
      cp -f "$TMP/band.png" "$RUN_DIR/$bstamp-band-$key.png" 2>/dev/null
      return 0
    fi
  done <"$TMP/band-hits.txt"
  return 1
}

# 深底白字的控件单独一档：只裁这一颗，不补 pad（bench5 量的就是这块框，补了 pad 数就变了）。
# 两档并跑：×1 收「今日已点亮」，×2 收「立即点亮」。
pill_pass() { # $1 = key, $2 = 截图 -> finder 结果写 stdout
  local key=$1 png=$2
  local v="PILL_$key" spec geo x0 y0 cw ch iw ih div psm out bstamp
  local -a labels=()
  local l av ovv ov bsx bsy boxx boyy
  spec=${!v:-}
  [ -n "$spec" ] || return 1
  # 默认还是「反色 + 硬阈值」那档（深底白字）。PILL_MODE_<key>=color 的控件相反：
  # 字和底靠颜色分开，一转灰度就糊在一起，10-20 频道页那颗抽福袋就是这种。
  local mv="PILL_MODE_$key"
  local mode
  mode=${!mv:-inv}
  [ "${TAP_W:-0}" -gt 0 ] 2>/dev/null || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c 'import PIL' >/dev/null 2>&1 || return 1
  av="ALIAS_$key"
  [ -n "${!av:-}" ] || return 1
  while IFS= read -r l; do labels+=("$l"); done < <(labels_of "$key")
  [ ${#labels[@]} -gt 0 ] || return 1
  ovv="OVERLAP_$key"; ov=${!ovv:-$MIN_OVERLAP}
  bstamp=$(date +%H%M%S)
  geo=$(PILL_PNG="$png" PILL_SPEC="$spec" python3 - <<'GEOM'
from PIL import Image
import os
im = Image.open(os.environ["PILL_PNG"])
W, H = im.size
x1, y1, x2, y2 = [float(t) for t in os.environ["PILL_SPEC"].split(",")]
xa, ya = max(0, int(x1 * W)), max(0, int(y1 * H))
xb, yb = min(W, int(x2 * W)), min(H, int(y2 * H))
print(xa, ya, xb - xa, yb - ya, W, H)
GEOM
) || return 1
  read -r x0 y0 cw ch iw ih <<<"$geo"
  [ "${cw:-0}" -gt 8 ] 2>/dev/null || return 1
  [ "${ch:-0}" -gt 8 ] 2>/dev/null || return 1
  for div in $PILL_SCALES; do
    out="$TMP/pill-$div.png"
    PILL_PNG="$png" PILL_OUT="$out" PILL_BOX="$x0 $y0 $cw $ch" \
    PILL_DIV="$div" PILL_TH="$PILL_TH" PILL_MODE="$mode" python3 - <<'CROP'
from PIL import Image, ImageOps
import os
im = Image.open(os.environ["PILL_PNG"])
x, y, w, h = (int(t) for t in os.environ["PILL_BOX"].split())
g = im.crop((x, y, x + w, y + h))
d = int(os.environ["PILL_DIV"])
if os.environ.get("PILL_MODE", "inv") != "color":
    k = int(os.environ["PILL_TH"])
    g = ImageOps.invert(g.convert("L")).point(lambda v: 0 if v < k else 255)
if d > 1:
    g = g.resize((g.width * d, g.height * d), Image.LANCZOS)
g.save(os.environ["PILL_OUT"])
CROP
    [ -s "$out" ] || continue
    cp -f "$out" "$RUN_DIR/$bstamp-pill-$key-x$div.png" 2>/dev/null
    for psm in $OCR_PSM_BAND $OCR_PSM; do
      tesseract "$out" stdout -l "$OCR_LANG" --psm "$psm" tsv \
        >"$TMP/pill-$psm-$div.tsv" 2>/dev/null || continue
      [ -s "$TMP/pill-$psm-$div.tsv" ] || continue
      # 和 band_pass 同一套换算：tsv 坐标是放大后的，除以 div；原点按整图比例回推
      bsx=$(awk -v a="$TAP_W" -v b="$iw" -v c="$div" 'BEGIN{printf "%.5f", a/b/c}')
      bsy=$(awk -v a="$TAP_H" -v b="$ih" -v c="$div" 'BEGIN{printf "%.5f", a/b/c}')
      boxx=$(awk -v a="$x0" -v b="$iw" -v w="$TAP_W" 'BEGIN{printf "%.1f", a/b*w}')
      boyy=$(awk -v a="$y0" -v b="$ih" -v h="$TAP_H" 'BEGIN{printf "%.1f", a/b*h}')
      finder --scale "$bsx" "$bsy" --offset "$boxx" "$boyy" \
        --min-conf "$OCR_MINCONF" tsv "$TMP/pill-$psm-$div.tsv" "$ov" "${labels[@]}"
    done
  done
  return 0
}

FIND_METHOD= FIND_XY= FIND_LABEL= FIND_SCORE=0
PAGE_ACT=                      # 点进活动页之后前台的 activity 名，用来发现被 BACK 退走

resolve() { # $1 = key -> 填 FIND_METHOD FIND_XY FIND_LABEL FIND_SCORE
  local out
  out=$(find_target "$1") || return 1
  IFS=$'\t' read -r FIND_METHOD FIND_XY FIND_LABEL FIND_SCORE <<<"$out"
  [ -n "$FIND_XY" ]
}

tap_xy() { adb_shell input tap "${1% *}" "${1#* }" >/dev/null 2>&1; }

dismiss_dialog() { # 认到整屏弹窗就关掉它；没认到返回 1
  local xy
  # 先看 ALIAS_dialog 有没有词，再去认屏幕。顺序不能反：
  # text_present 认不到字时会退回 COORD_dialog，而 ALIAS_dialog='' 时 find_target
  # 也会直接吐坐标——那样「没认到弹窗」和「认到弹窗」会走同一条路，变成盲枪，
  # 在任何一屏都去点右上角（本机 617,222）。09-27 和 10-07 那两次就是这么把自己退出活动页的。
  # ALIAS_dialog 留空 = 这条线整个停用，这是故意的，不是忘了配。
  if [ -z "${ALIAS_dialog:-}" ]; then
    log POP "ALIAS_dialog 是空的，dismiss_dialog 停用（不按 COORD_dialog 盲点）"
    return 1
  fi
  text_present dialog || return 1
  log POP "认到弹窗「$FIND_LABEL」，按 BACK 关掉"
  adb_shell input keyevent KEYCODE_BACK >/dev/null 2>&1
  sleep 2
  if text_present dialog; then
    xy=$(frac_xy "$COORD_dialog") || { log POP "BACK 关不掉，但点空间不知道，比例没法换算，收手"; return 0; }
    log POP "BACK 关不掉，点 X $xy（COORD_dialog=$COORD_dialog）"
    tap_xy "$xy"
    sleep 2
  fi
  return 0
}

back_on_page() { # 被 BACK 退出活动页了就重走一遍入口；$1 = 当前步骤名
  [ "$1" != "$TOP_RETRY_KEY" ] || return 0
  [ -n "$PAGE_ACT" ] || return 0
  local now; now=$(focused_act)
  [ "$now" = "$PAGE_ACT" ] && return 0
  log STEP "$1 时发现前台已经变成 $now，重走 $TOP_RETRY_KEY 回活动页"
  do_step "$TOP_RETRY_KEY"
}

do_step() { # $1 = key
  local key=$1 topped=0 dialog=0 proved=0 entered=0 now
  while :; do
    if resolve "$key"; then
      # 首页那个入口只认字不认坐标，认不到字多半是页面没在顶端：滑回最顶端再认一轮
      if [ "$key" = "$TOP_RETRY_KEY" ] && [ "$FIND_METHOD" = coord ] && [ "$topped" = 0 ]; then
        topped=1
        log STEP "$key 没认到字，先滑到页面最顶端再认一次"
        scroll_to_top "$TOP_SWIPES"
        continue
      fi
      # 核实/恢复这一路上只认字：10-11 第三枪就是「分数=0 的 COORD_bag」盲点，
      # 屏幕已经换成新版式，那一枪点的是别处。认不到字就当场收手，别拿固定坐标赌。
      if [ "$RECOVERY_NO_COORD" = true ] && [ "$IN_RECOVERY" = 1 ] && [ "$FIND_METHOD" = coord ]; then
        log FAIL "$key 在核实/恢复环节只认出固定坐标（$FIND_XY 分数=$FIND_SCORE），拒绝盲点"
        return 1
      fi
      log STEP "$key 用 $FIND_METHOD 点 $FIND_XY [$FIND_LABEL 分数=$FIND_SCORE]"
      tap_xy "$FIND_XY"
      sleep "$STEP_WAIT"
      now=$(focused_act)
      log STEP "$key 点完，前台 $now"
      # 点完还在首页 = 这一枪被盖在上面的东西吃了。见配置区 ENTRY_RETRY 那段（10-30 那张弹窗）。
      if [ "$key" = "$TOP_RETRY_KEY" ] && is_home_page "$now"; then
        if [ "$entered" -lt "$ENTRY_RETRY" ]; then
          entered=$((entered + 1))
          log STEP "点完还在首页，多半被弹窗吃了；按 BACK 退掉再点一次入口（第 $entered/$ENTRY_RETRY 次）"
          # 重试这一路只认字：BACK 有可能顺手把人退出拼多多，那时候拿 COORD_subsidy
          # 在来历不明的屏上补一枪，就是 10-11 那条「读不到就不点」要挡的东西。
          IN_RECOVERY=1
          adb_shell input keyevent KEYCODE_BACK >/dev/null 2>&1
          sleep "$ENTRY_RETRY_WAIT"
          continue
        fi
        log FAIL "入口连着 $((entered + 1)) 枪都还在首页，盖着的东西 BACK 也退不掉，收手"
        return 1
      fi
      # 记下活动页那个 activity 叫什么，后面万一被 BACK 退走就好判断
      [ "$key" = "$TOP_RETRY_KEY" ] && PAGE_ACT=$now
      if [ "$key" = "$PROVE_KEY" ] && ! proof_ok "$key"; then
        proved=$((proved + 1))
        if [ "$proved" -ge "$PROVE_MAX" ]; then
          log FAIL "$key 连着 $proved 次都没进对页面，收手"
          return 1
        fi
        log STEP "按 BACK 退回活动页，等轮播下一帧（接下来这一枪起走核实路线，只认字）"
        IN_RECOVERY=1
        adb_shell input keyevent KEYCODE_BACK >/dev/null 2>&1
        sleep 3
        continue
      fi
      # 这一枪成了就把核实标记撤掉：后面 点亮 那一步还是走主线，胶囊的坐标兜底照旧能用
      IN_RECOVERY=
      return 0
    fi
    if [ "$dialog" = 0 ] && dismiss_dialog; then
      dialog=1
      # BACK 是全局的，关掉弹窗的同时也可能顺手把人退出活动页（09-27 就是这样），
      # 前台换了页面就得重走入口，别站在首页上找抽福袋
      back_on_page "$key" || return 1
      continue
    fi
    log FAIL "$key 没找到"
    return 1
  done
}

# ---------------------------------------------------------- 今天是否已完成

marker_path() { printf '%s/.done-%s\n' "$EVIDENCE_DIR" "$(date +%F)"; }

mark_done() {
  mkdir -p "$EVIDENCE_DIR" 2>/dev/null
  : >"$(marker_path)" 2>/dev/null
}

text_present() { # $1 = key -> 屏幕上读得到 ALIAS_$1 就返回 0，只扫一轮
  local keep=$FIND_RETRY rc=1 v="ALIAS_$1"
  [ -n "${!v:-}" ] || return 1
  FIND_RETRY=1
  # 只认字：resolve 认不到字会退回 COORD_*，那是坐标兜底，不代表屏幕上真有这几个字
  if resolve "$1" >/dev/null 2>&1 && [ "$FIND_METHOD" != coord ]; then
    rc=0; log CHECK "屏幕上读到「$FIND_LABEL」于 $FIND_XY"
  fi
  FIND_RETRY=$keep
  return $rc
}

pend_scan() { # 认到 pend 那一档之后，把屏幕上那整句话抄下来并抠出天数 N
  # finder 只给命中的三五个字，抄不出整句，也拿不到 N，所以再拿整页识别复读一遍。
  # 一档读不出天数就换下一档（PEND_PSM）：图只截一次，换的是识别模式，不重碰手机。
  # 读不到就一律留空：宁可推送里少一句话，也不在屏幕上没有这几个字时凭空写倒数天数。
  local txt line days psm got=
  have tesseract || return 1
  grab_shot "$TMP/pend.png" || return 1
  PEND_LINE=; PEND_DAYS=
  for psm in $PEND_PSM; do
    txt=$(tesseract "$TMP/pend.png" stdout -l "$OCR_LANG" --psm "$psm" 2>/dev/null \
          | tr -d ' \t\r')
    [ -n "$txt" ] || continue
    line=$(printf '%s\n' "$txt" | grep -E -e "$PEND_LINE_RE" | head -3 | tr '\n' ' ')
    [ -n "$line" ] || continue
    [ -n "$PEND_LINE" ] || PEND_LINE=${line% }
    days=$(printf '%s' "$line" | grep -E -o "$PEND_DAYS_RE" | head -1 | tr -dc '0-9')
    [ -n "$days" ] || continue
    PEND_DAYS=$days; got=$psm
    break
  done
  log CHECK "待兑换那一行抄到「${PEND_LINE:-整句都没读到}」，天数=${PEND_DAYS:-没读到}${got:+（psm $got 读出的）}"
  [ -n "$PEND_DAYS" ]
}

pend_hit() { # 屏幕上读到「任务已完成/待兑换」那一档 -> 0，并把原文留给推送用
  text_present pend || return 1
  PEND_SEEN=1; PEND_LABEL=$FIND_LABEL
  pend_scan
  return 0
}

light_count() { # 读活动页那行进度提示里的 N，$1 = 存证据用的标签；读不到就输出空
  local stamp; stamp=$(date +%H%M%S)
  local txt n
  have tesseract || return 1
  grab_shot "$TMP/count.png" || return 1
  cp -f "$TMP/count.png" "$RUN_DIR/$stamp-count-$1.png" 2>/dev/null
  # 整页 psm 6 才认得出这行；再把换行和空格抹掉，「再点亮 4 次」和「再点亮4次」就同一个形状
  txt=$(tesseract "$TMP/count.png" stdout -l "$OCR_LANG" --psm "$OCR_PSM_PAGE" 2>/dev/null \
        | tr -d ' \t\r\n')
  n=$(printf '%s' "$txt" | grep -oE "(${COUNT_TEXT})[0-9]{1,2}" | head -1 | tr -dc '0-9')
  [ -n "$n" ] || return 1
  printf '%s\n' "$n"
}

proof_ok() { # 轮播位那一格点对了才会落到活动页：进度行读得到才算进对
  local n
  n=$(light_count "prove-$1") || n=
  [ -n "$n" ] && { log STEP "$1 点完读到进度行里的 $n 次，页面进对了"; return 0; }
  # 10-11 实测：7 天点亮跑满后那一整行进度被「点亮任务已完成…3天后可兑换」顶掉了，
  # 这时候读不到进度不等于停错帧。认到这几个词就是进对页面了，只是没得可点，
  # 剩下交给 light 那一步的 pend 检查报人工。
  if pend_hit; then
    log CHECK "$1 点完读不到进度行，但屏幕上写着「$PEND_LABEL」：任务已完成、奖励在等人兑换"
    return 0
  fi
  # 10-25/10-26 两天各 3 枪全栽在这一档上，报的是 rc=5（当时那条标题写「PDD 失败」，
  # 10-27 起这一档是「PDD ❌ 退出码 5」），而屏幕上根本没坏：
  # 她把兑换到的券用掉了，顶部那一行换成「5折 最高减15元 已使用」，进度行整行没了、
  # 「任务已完成/待兑换」那三句也一个都不在，pend 那条救不上。认到 done 那一档
  # （已点亮/明日再来/明天再来/已使用）说明页面进对了、这一轮已经到头；到底算哪种终态，
  # 交给下一步 light 的 CHECK_DONE_BEFORE 判，这里不替它下结论。
  if text_present done; then
    log CHECK "$1 点完读不到进度行，但屏幕上写着「$FIND_LABEL」：页面进对了，这一轮没得可点"
    return 0
  fi
  log FAIL "$1 点完读不到进度行，多半停在轮播的另一帧"
  return 1
}

browse_page() { # 屏幕上是「滑动浏览当前页面10秒即可点亮」那一屏就滑够时长，然后退回活动页
  local i bstamp t0 t1 n=0 h span y1 y2 bx
  text_present browse || return 1
  bstamp=$(date +%H%M%S)
  grab_shot "$RUN_DIR/$bstamp-browse-before.png" 2>/dev/null
  # 单次不超过半屏：滑过头会把进度卡甩到屏幕外面（10-09 那次就是滑太狠）
  h=${TAP_H:-1280}
  [ "${h:-0}" -gt 100 ] 2>/dev/null || h=1280
  span=$(( h / 2 ))
  y1=$(( h * 8 / 10 ))
  y2=$(( y1 - span ))
  [ "${y2:-0}" -ge 2 ] 2>/dev/null || y2=2
  bx=$(frac_x "$BROWSE_X")
  log CHECK "这一屏要滑满 $BROWSE_SECONDS 秒：x=$bx 单次 $(( y1 - y2 ))px（半屏 $span px），按压 ${BROWSE_DUR}ms 不间断"
  t0=$(date +%s)
  while :; do
    t1=$(date +%s)
    [ $(( t1 - t0 )) -lt "$BROWSE_SECONDS" ] || break
    n=$(( n + 1 ))
    if [ "$n" -gt "$BROWSE_MAX_SWIPES" ] 2>/dev/null; then
      log WARN "已经滑了 $BROWSE_MAX_SWIPES 下还没到 $BROWSE_SECONDS 秒，停在这里"
      break
    fi
    adb_shell input swipe "$bx" "$y1" "$bx" "$y2" "$BROWSE_DUR" >/dev/null 2>&1
    [ "$BROWSE_WAIT" -gt 0 ] 2>/dev/null && sleep "$BROWSE_WAIT"
  done
  t1=$(date +%s)
  grab_shot "$RUN_DIR/$bstamp-browse-after.png" 2>/dev/null
  log STEP "滑了 $n 下、耗时 $(( t1 - t0 ))s（表 $BROWSE_SECONDS s），证据 $bstamp-browse-{before,after}.png"
  if [ "$BROWSE_PROVE" = true ]; then
    if text_present browse; then
      log WARN "滑完横幅还在，进度可能没算上（倒计时没走完？）"
    else
      log CHECK "滑完横幅已经消失，这一屏过了"
    fi
  fi
  if [ "$BROWSE_BACK" = true ]; then
    adb_shell input keyevent KEYCODE_BACK >/dev/null 2>&1
    sleep 3
  fi
  return 0
}

clear_popup_once() { # 证据读不到时才用：认到浮层上的关闭/暂不才点一下，没认到什么都不做
  resolve popup || return 0
  [ "$FIND_METHOD" = coord ] && return 0
  log POP "屏幕上盖着浮层「$FIND_LABEL」，点掉再读一次证据"
  tap_xy "$FIND_XY"
  sleep "$POPUP_WAIT"
}

take_prize_overlay() { # 只在已经读到奖励浮层那两行字之后调用：认得到「开心收下」点认到的，认不到退 COORD_take
  # 浮层那两行字本身已经是点着了的凭据，这一枪收不收都不影响本轮判成功。
  # 退的那颗中心只在 10-10 那一帧上量过；残留风险是浮层改版、按钮不在原处，
  # 那一枪就打在浮层底下那一屏的东西上——所以日志必须分清「认到字」和「按中心」，
  # 出问题时能从日志里看出这一枪是盲的。
  local keep=$FIND_RETRY
  FIND_RETRY=1
  if resolve take; then
    if [ "$FIND_METHOD" = coord ]; then
      log POP "浮层上读不到「开心收下」，按量好的中心收 $FIND_XY（分数=0）"
    else
      log POP "浮层上认到「$FIND_LABEL」于 $FIND_XY，点它收下"
    fi
    tap_xy "$FIND_XY"
  else
    log POP "浮层上读不到「开心收下」，中心也没配，什么都不点"
  fi
  FIND_RETRY=$keep
  sleep "$POPUP_WAIT"
}

verify_light() { # $1 = 点之前的 N, $2 = 那一枪用的是哪种方式；点没点着只认屏幕上的证据
  local before=$1 method=$2 after=
  VERIFY_WHY=
  # 新版式里点亮这一枪会跳到「消费券」这一页。10-18 真机把滑完那一屏整页存下来了：
  # 顶部只有「消费券」标题栏和返回箭头，进度卡「7天内再点亮N次必得」**根本不在这一页上**，
  # 所以原地判定（滚回顶部、「今日已点亮」、进度行、奖励浮层、pend、点浮层复读）在这一页上
  # 全是白耗 —— 10-18 那次这一段跑了 99 秒，一个字段都没读到。
  # 浏览这一路改成先按 BACK 离开这一页，再在落到的那一页上做判定。
  # BACK 落在哪一页也实测过：不是活动页，是**百亿补贴频道页**（顶部「百亿补贴 搜索补贴 搜低价」，
  # 轮播第二格就是「抽福袋」胶囊）—— 10-09 那条旧注释说对了，我 10-17 写的「BACK 正好回到带进度卡那一页」是错的。
  # 所以在频道页上认到「抽福袋」就再点一次胶囊回活动页，进度卡在那一页上；认不到字什么都不点，
  # 交给下面那条备用路线。
  # 残留风险（没测到、也没法用坐标挡住，先记在这里）：活动页下面那张卡上写着「邀好友抽福袋」，
  # 中心实测 y=948（110705-count-after.png 整页 psm6 的 邀/福/袋 三个框 937..959），
  # 而频道页那颗胶囊两个版式分别在 y=524 和 y=894 —— 54 个点的间距，拿 y 划不出「这是频道页不是活动页」。
  # 真要在活动页上误点它，后面 `light_count after-reenter` 读空、原地链读空、备用路线读空，
  # 最后是 rc=6 + 推送，不会悄悄报成功。
  if browse_page; then
    log CHECK "浏览完了，按 BACK 离开消费券页"
    adb_shell input keyevent KEYCODE_BACK >/dev/null 2>&1
    sleep "$STEP_WAIT"
    after=$(light_count after-back) || after=
    [ -n "$after" ] && log CHECK "进度行 $after 次是 BACK 回上一页读到的"
    if [ -z "$after" ] && text_present bag; then
      log CHECK "BACK 落在频道页，点「$FIND_LABEL」胶囊回活动页"
      tap_xy "$FIND_XY"
      sleep "$STEP_WAIT"
      after=$(light_count after-reenter) || after=
      [ -n "$after" ] && log CHECK "进度行 $after 次是重进活动页读到的"
    fi
  fi
  if [ -z "$after" ]; then
    if text_present done; then
      log CHECK "点完读到「$FIND_LABEL」，这一屏自己说了算完成"
      return 0
    fi
    after=$(light_count after) || after=
  fi
  # 进度行读不到，可能是广告浮层正好盖住那一行：点掉它再读一次。
  # 只有已经要判失败时才走这步，顺带别在正常那一枪上多点三下。
  if [ -z "$after" ]; then
    # 10-10 版式：发放后盖在屏幕上的「恭喜提前锁定限时翻倍券」会把进度行和胶囊一起挡掉。
    # 这段字只有这个浮层才有，读到就当证据，不再走重进福袋页那条备用路线。
    if text_present prize; then
      log CHECK "进度行读不到，但屏幕上写着奖励浮层「$FIND_LABEL」，这就是点着了的凭据"
      take_prize_overlay
      return 0
    fi
    # 进度行整个消失的第二种可能：这一轮 7 天已经跑满，页面换成「任务已完成…待兑换」。
    # 回报 4，让上层按「要她动手」处理，别当没点着（rc=6）也别当点着了（lit=3）。
    if pend_hit; then
      log CHECK "进度行读不到，屏幕上写的是「$PEND_LABEL」：点亮任务已完成，奖励在等人兑换"
      return 4
    fi
    clear_popup_once
    if text_present done; then
      log CHECK "点掉浮层读到「$FIND_LABEL」，这一屏自己说了算完成"
      return 0
    fi
    after=$(light_count after2) || after=
  fi
  # 点掉浮层还是读不到，才退回去重进福袋页 —— 那是备用路线，不是主线
  if [ -z "$after" ] && [ -n "$PAGE_ACT" ]; then
    log WARN "原地读不到进度，回活动页重进一次福袋页"
    # 备用路线上认不到字就收手，不许退回固定坐标（10-11 的 rc=5 就是这么来的）
    IN_RECOVERY=1
    do_step "$TOP_RETRY_KEY" >/dev/null 2>&1
    local prc=0
    do_step "$PROVE_KEY" || prc=$?
    IN_RECOVERY=
    [ "$prc" = 0 ] || {
      VERIFY_WHY="重进福袋页失败，进度读不到"
      log FAIL "$VERIFY_WHY，点亮没法核实"; return 1; }
    after=$(light_count after) || after=
  fi
  if [ -n "$before" ] && [ -n "$after" ]; then
    if [ "$after" -lt "$before" ] 2>/dev/null; then
      log CHECK "进度从 $before 次变成 $after 次，这枪真点着了"
      return 0
    fi
    VERIFY_WHY="屏幕上进度行的 $after 次没变小（点前 $before 次），这一枪没打进去"
    log FAIL "$VERIFY_WHY"; return 1
  fi
  # 进度行读不到：认到字才点的那一枪可以放过，纯坐标那一枪不能算成功
  if [ "$method" = coord ]; then
    VERIFY_WHY="读不到进度行里那个次数，而这一枪只有坐标兜底能打到，无法核实（版面大概又变了）"
    log FAIL "$VERIFY_WHY"; return 1
  fi
  log WARN "读不到进度行，但这一枪点的是认到的字，按原样算过"
  return 0
}

# ------------------------------------------------------------------ 流程

scroll_to_top() { # 把信息流拉回顶部，那一格的相对位置才和校准时一致；$1 = 滑几次
  local i n=${1:-$SCROLL_TOP} x y1 y2
  [ "${n:-0}" -gt 0 ] 2>/dev/null || return 0
  x=$(frac_x "$SWIPE_X"); y1=$(frac_y "$TOP_SWIPE_Y1"); y2=$(frac_y "$TOP_SWIPE_Y2")
  for i in $(seq 1 "$n"); do
    adb_shell input swipe "$x" "$y1" "$x" "$y2" "$SWIPE_DUR" >/dev/null 2>&1
    sleep "$SWIPE_WAIT"
  done
}

clear_popups() {
  local i
  for i in $(seq 1 "$POPUP_MAX"); do
    if ! resolve popup; then
      [ "$i" = 1 ] && log POP "没有弹窗"
      return 0
    fi
    log POP "第 $i 次，用 $FIND_METHOD 点 $FIND_XY [$FIND_LABEL]"
    tap_xy "$FIND_XY"
    sleep "$POPUP_WAIT"
  done
  log WARN "弹窗连点 $POPUP_MAX 次都没关掉"
}

HOME_ACT=com.xunmeng.pinduoduo.ui.activity.MainFrameActivity   # 拉起首页用；PDD 自己会再跳到 HomeActivity
HOME_ACT_ALT=com.xunmeng.pinduoduo.ui.activity.HomeActivity
LAUNCH_BACKS=3                      # 没落在首页就按几次 BACK 往回退

launch_app() {
  local i
  [ "$RESTART_APP" = true ] && { adb_shell am force-stop "$PKG" >/dev/null 2>&1; sleep 1; }
  # 不能用 monkey：它会复用上次残留的 task，把待支付订单页 NewPageActivity 拉到前台，
  # 首页入口就永远读不到。显式 am start 首页 activity 才是干净的起点。
  adb_shell am start -n "$PKG/$HOME_ACT" >/dev/null 2>&1 \
    || adb_shell am start -n "$PKG/$HOME_ACT_ALT" >/dev/null 2>&1
  log RUN "启动 $HOME_ACT，等 ${LAUNCH_WAIT}s"
  sleep "$LAUNCH_WAIT"
  for i in $(seq 1 "$LAUNCH_BACKS"); do
    is_home_page && { [ "$i" = 1 ] && log RUN "已经在首页"; return 0; }
    log RUN "前台是 $(focused_act)，不是首页，再拉一次"
    adb_shell am start -n "$PKG/$HOME_ACT" >/dev/null 2>&1
    sleep 3
  done
  is_home_page && { log RUN "重拉后到首页"; return 0; }
  log RUN "重拉 $LAUNCH_BACKS 次还不在首页，按 BACK 退回"
  adb_shell input keyevent KEYCODE_BACK >/dev/null 2>&1
  sleep 3
  is_home_page || log WARN "还是不在首页，接着往下走"
}

focused_act() { # 焦点窗口的 activity 全名
  adb_shell dumpsys window 2>/dev/null | tr -d '\r' \
    | awk '/mCurrentFocus/ {for (i=1;i<=NF;i++) if ($i ~ /\//) {split($i,a,"/"); print a[2]; exit}}'
}

is_home_page() { # 焦点窗口是不是 PDD 的首页（MainFrameActivity / HomeActivity）
  # $1 可以传一个现成的 activity 名（do_step 刚查过焦点，没必要再问一次手机）
  local act=${1:-}
  [ -n "$act" ] || act=$(focused_act)
  case "$act" in
    *"$HOME_ACT"*|*"$HOME_ACT_ALT"*) return 0 ;;
  esac
  return 1
}

scroll_phase() {
  local i x y1 y2
  x=$(frac_x "$SWIPE_X"); y1=$(frac_y "$SWIPE_Y1"); y2=$(frac_y "$SWIPE_Y2")
  log RUN "下滑 x=$x $y1->$y2（比例 $SWIPE_X $SWIPE_Y1->$SWIPE_Y2）时长=${SWIPE_DUR}ms 次数=$SWIPE_COUNT"
  for i in $(seq 1 "$SWIPE_COUNT"); do
    adb_shell input swipe "$x" "$y1" "$x" "$y2" "$SWIPE_DUR" >/dev/null 2>&1
    log RUN "下滑 $i/$SWIPE_COUNT"
    sleep "$SWIPE_WAIT"
  done
}

notify() { # $1 = 推送标题, $2 = 正文
  [ -n "$PUSH_URL" ] || return 0
  have curl || { log WARN "没有 curl，跳过推送"; return 0; }
  local out
  out=$(curl -sk -m 15 -G --data-urlencode "title=$1" --data-urlencode "desp=$2" "$PUSH_URL" 2>&1)
  if printf '%s' "$out" | grep -q '"code":0'; then
    log PUSH "已推送: $1"
  else
    log WARN "推送失败: $out"
  fi
}

prune_evidence() {
  [ -d "$EVIDENCE_DIR" ] || return 0
  find "$EVIDENCE_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} + 2>/dev/null
}

ledger_read() { # 账本里现在记着几天；文件不在/不是纯数字都算"没记过"
  local raw
  raw=$(head -1 "$PAUSE_FILE" 2>/dev/null | tr -d ' \t\r')
  case $raw in
    ''|*[!0-9]*) return 1 ;;
  esac
  printf '%s' "$raw"
}

ledger_write() { # $1 = 记几天, $2 = 为什么是这个数
  mkdir -p "$(dirname "$PAUSE_FILE")" 2>/dev/null
  if printf '%s\n' "$1" >"$PAUSE_FILE" 2>/dev/null; then
    PAUSE_WRITTEN=$1
    log RUN "$PAUSE_FILE 记成 $1：$2"
    return 0
  fi
  log FAIL "$PAUSE_FILE 写不进去（权限或目录）：$2"
  return 1
}

pend_pause_write() { # 待兑换这一屏：屏幕上那个 N 读得到就照抄，读不到就把账上的数减一天
  if [ -n "$PEND_DAYS" ]; then
    ledger_write "$PEND_DAYS" "屏幕上读到「$PEND_DAYS 天后可兑换」，照抄"
    return 0
  fi
  local had
  if had=$(ledger_read); then
    [ "$had" -gt 0 ] || { log RUN "认到待兑换但没读到天数，账上本来就是 0，不动它"; return 1; }
    ledger_write "$((had - 1))" "今天没读到「N天后可兑换」里的天数，账上的 $had 天往下减 1"
    return 0
  fi
  log WARN "认到待兑换、没读到天数、账本里也没有能减的数字 —— $PAUSE_FILE 一个字都没写"
  return 1
}

cmd_run() {
  local marker=$(marker_path) rc=0 key code=4 lit=0 before= last_act= vrc=0 pend_msg= exc_msg=
  mkdir -p "$RUN_DIR" || return 73
  LOGFILE=$RUN_DIR/run.log
  if [ -f "$marker" ] && [ "${1:-}" != force ]; then
    log DONE "$marker 说明今天已经做完了，收工（要重来就: pdd.sh run force）"
    return 0
  fi
  # 没有整页 OCR 就等于瞎子：进度行、已点亮、抽福袋全读不到，只剩拿坐标猜。当场停，别跑半程再报「没找到」
  if ! have tesseract; then
    log FAIL "这台机器上没有 tesseract，屏幕读不了，不猜坐标"
    notify "PDD ❌ 缺 tesseract" "整页识别的程序不在了，脚本拒绝用坐标瞎点。装上再跑：apt-get install tesseract-ocr tesseract-ocr-chi-sim"
    return 78
  fi
  log RUN "device=$DEVICE 证据=$RUN_DIR 命中门槛>=$MIN_OVERLAP OCR=开"
  ensure_device || { log FAIL "adb 设备 $DEVICE 掉线"; notify "PDD ❌ 设备掉线" "adb $DEVICE 连不上"; return 2; }
  read_resolution
  log RUN "点空间 ${TAP_W}x${TAP_H}"
  wake_screen || { log FAIL "手机锁着，不猜密码"; notify "PDD ❌ 手机锁屏" "有锁屏密码，脚本不猜"; return 3; }
  launch_app
  if require_pdd launch; then
    clear_popups
    scroll_to_top
    for key in $STEPS; do
      require_pdd "$key" || { rc=$code; break; }
      if [ "$key" = "$CHECK_DONE_BEFORE" ]; then
        dismiss_dialog      # ALIAS_dialog 现在是空的，这行等于不做事，留着以防哪天又配回弹窗词
        back_on_page "$key" || { rc=$code; break; }
        # 只有站在点亮那一屏上才判状态：首页信息流里也可能冒出「已使用」三个字
        if text_present done; then
          lit=1; DONE_WORD=${FIND_LABEL//[[:space:]]/}
          log DONE "屏幕上写着「$FIND_LABEL」，算完成，没重复点"; break
        fi
        if text_present exchange; then
          lit=2; log WARN "屏幕上是立即兑换，这步得人来点"; break
        fi
        if pend_hit; then
          lit=4
          log WARN "屏幕上是「$PEND_LABEL」：点亮任务已完成、奖励在等人兑换，脚本不代点"; break
        fi
        before=$(light_count before) || before=
        log CHECK "既不是已使用也不是立即兑换，照原样点 $key（点前进度 ${before:-读不到} 次）"
      fi
      do_step "$key" || { rc=$code; break; }
      if [ "$key" = "$CHECK_DONE_BEFORE" ]; then
        sleep "$STEP_WAIT"
        verify_light "$before" "$FIND_METHOD"; vrc=$?
        case $vrc in
          0) lit=3 ;;
          4) lit=4 ;;
          *) rc=6; break ;;
        esac
      fi
      code=$((code + 1))
    done
  else
    rc=7
  fi
  if [ $lit -eq 1 ]; then
    mark_done
    ledger_write 0 "这一轮是正常点亮周期，没有待兑换要记"
  elif [ $lit -eq 4 ]; then
    # 待兑换是这一轮的正常终态：今天的完成标记照写（不然当天还会再被叫起来碰手机），
    # 再把屏幕上那个「N天后可兑换」记进账本 —— 这个数不挡路，只给她看还剩几天
    mark_done
    pend_pause_write
    if [ -n "$PEND_DAYS" ]; then
      pend_msg="$PAUSE_FILE 记成 $PEND_DAYS：屏幕上那句的天数，照抄。"
    elif [ -n "$PAUSE_WRITTEN" ]; then
      pend_msg="$PAUSE_FILE 记成 $PAUSE_WRITTEN：今天没读到天数，按账上原来的数往下减了一天。"
    else
      pend_msg="没从屏幕上读到「N天后可兑换」里的天数，账本也没能减的数，$PAUSE_FILE 一个字都没写。"
    fi
    # 10-16 她回的「1要，2去」里的 2 就是这一次 BACK —— 去掉了：待兑换这一轮到这里就结束，
    # 按键一个都不再放 —— 手机上停留的就是刚读到「任务已完成」的那一屏，app 留在前台，
    # 只发推送。以前那一次 BACK 在 10-12/10-13 实测连 activity 都没换（screen= 仍是
    # NewPageActivity），退页这件事本来就没被证明，留着只多一个不可控的动作。
  elif [ $lit -eq 2 ]; then
    # 屏幕上换成「立即兑换」的那一刻，倒数就已经走完了：账本清零，
    # 免得 pdd-pause 一直挂着 1 天、读起来像还有得等。标记不写（这一轮没做点亮，
    # 明天 10:00 该照常醒）；兑换那一下仍然只喊她，不代点。
    if ledger_write 0 "屏幕上就是「立即兑换」，兑换窗口已到，倒数作废"; then
      exc_msg="$PAUSE_FILE 已记 0：倒数走完，账上不再挂着还剩几天。"
    else
      exc_msg="$PAUSE_FILE 这次没写进去，原样留着，理由见 run.log。"
    fi
  elif [ $rc -eq 0 ] && { [ $lit -eq 0 ] || [ $lit -eq 3 ]; }; then
    scroll_phase
    mark_done
    ledger_write 0 "点亮又跑起来了，兑换倒数作废"
  fi
  last_act=$(focused_act)          # 这行必须在关应用/ HOME 之前：按完再读就只剩桌面了
  [ "$lit" = 4 ] && [ -z "$VERIFY_WHY" ] && VERIFY_WHY="点亮任务已完成，奖励在等人兑换（pend 档，不算错误）"
  # 2 和 4 都不关 app（$NO_CLOSE_LIT），也不多放按键：2 停在「立即兑换」那一屏等她接手，
  # 4 停在刚读到「任务已完成」的那一屏，两种都只发推送。
  NO_CLOSE=0
  case " $NO_CLOSE_LIT " in *" $lit "*) NO_CLOSE=1 ;; esac
  if [ "$rc" = 0 ] && [ "$CLOSE_APP_ON_OK" = true ] && [ "$NO_CLOSE" != 1 ]; then
    log RUN "正常完成，关掉 $PKG"
    adb_shell am force-stop "$PKG" >/dev/null 2>&1
    adb_shell input keyevent KEYCODE_HOME >/dev/null 2>&1
  elif [ "$rc" = 0 ] && [ "$NO_CLOSE" = 1 ]; then
    # 她要看的那一屏：既不 force-stop 也不按 HOME，手机就停在 app 里
    log RUN "这轮不关 app（lit=$lit），手机停在拼多多里等她"
  else
    adb_shell input keyevent KEYCODE_HOME >/dev/null 2>&1
  fi
  printf 'result=%s\nlit=%s\nsteps=%s\ndate=%s\nevidence=%s\nscreen=%s\nwhy=%s\n' \
    "$([ "$rc" = 0 ] && echo ok || echo "failed:$rc")" "$lit" "$STEPS" "$(date +%F)" "$RUN_DIR" \
    "${last_act:-读不到}" "${VERIFY_WHY:-}" \
    >"$RUN_DIR/summary.txt"
  prune_evidence
  # 标题：不写日期，五档一眼分开（她 10-27 定的口径）。日期在正文和 summary.txt 里，没丢。
  case $lit in
    2) notify "PDD 需人工" \
"走到点亮那一步，屏幕上写的是「立即兑换」，脚本不代点。
app 和这一屏都给你留着，直接接手就行。
$exc_msg
证据 $RUN_DIR" ;;
    4) notify "PDD 💡" \
"进度那一行（原来写着「N天内点亮X次必得」）没了，现在是：${PEND_LINE:-${PEND_LABEL:-点亮任务已完成，N天后可兑换}}
$pend_msg
今天的完成标记已写。这一轮没在手机上多点一个字、多按一个键，app 就停在刚读到这句话的这一屏 —— 等到屏幕上换成「立即兑换」那天，推送标题换成「需人工」，那一下同样只喊你不代点。
证据 $RUN_DIR" ;;
    *) if [ "$rc" = 0 ]; then
         local title="PDD ✅"
         case $DONE_WORD in *已使用*) title="PDD 已使用" ;; esac
         notify "$title" \
"$([ $lit -eq 1 ] && echo "屏幕上写着「${DONE_WORD:-已点亮/已使用}」，没重复点，也没往下点" || echo '三步点完，活动页那行进度核实过 + 下滑跑完')
步骤 $STEPS
证据 $RUN_DIR"
       elif [ "$rc" = 6 ]; then
         notify "PDD ⬛ 退出码 6" \
"${VERIFY_WHY:-点完了但屏幕上进度行的次数没变小}
当失败处理，没写今天的完成标记，明天会自己再来一遍。
最后停在 ${last_act:-读不到} 这一屏，证据 $RUN_DIR"
       else
         notify "PDD ❌ 退出码 $rc" \
"最后停在 ${last_act:-读不到} 这一屏（登录页/验证码之类也长这样，脚本不代填）。
看 $RUN_DIR/run.log"
       fi ;;
  esac
  log RUN "退出码=$rc lit=$lit"
  return $rc
}

cmd_probe() {
  ensure_device || return 2
  read_resolution
  mkdir -p "$RUN_DIR"
  FIND_RETRY=1
  ui_dump "$RUN_DIR/probe.xml" || { log FAIL "uiautomator dump 失败"; return 1; }
  grab_shot "$RUN_DIR/probe.png"
  log PROBE "点空间 ${TAP_W}x${TAP_H}，截图 $RUN_DIR/probe.png（下面 COORD_ 行已按这个点空间折成 0..1 比例）"
  log PROBE "所有带文字的节点（x  y  可点  文字）"
  finder nodes "$RUN_DIR/probe.xml"
  local key out
  for key in popup done $STEPS; do
    out=$(find_target "$key" 2>/dev/null) || { printf '  %-9s 不在屏幕上\n' "$key"; continue; }
    printf '  %-9s %s\n' "$key" "$(printf '%s' "$out" | tr '\t' ' ')"
    printf 'COORD_%s=%s\n' "$key" "$(xy_frac "$(printf '%s' "$out" | cut -f2)")"
  done
}

cmd_find() {
  [ -n "${1:-}" ] || { echo "用法: pdd.sh find <key>" >&2; return 2; }
  ensure_device || return 2
  read_resolution
  local out
  out=$(find_target "$1") || { echo "没找到: $1" >&2; return 1; }
  printf '%s\n' "$out" | tr '\t' ' '
}


# ------------------------------------------------------------------ 回放
# 拿已经存下来的证据（截图 + XML）离线重跑「找目标」的判断。不碰手机、不需要 adb，
# 也不需要 tesseract（除非加 --ocr）。PDD 改版之后先在这里把配置筛一遍，筛得动了
# 再上机器验真——比每次烧一次真机十分钟便宜得多。
#
#   pdd.sh replay <证据目录>                          重放这一轮里每个 XML 帧
#   pdd.sh replay <证据目录> --size 720x1280          手动给点空间（区域闸门要用）
#   pdd.sh replay <证据目录> --label <key> <标签...>  临时换一组文案重打分
#   pdd.sh replay <证据目录> --ocr                    顺带把存下来的截图也过一遍 OCR
#   pdd.sh replay <证据目录> --scan                   每帧都试所有 key（慢，用来翻资产）
#   pdd.sh replay [证据根目录] --all                  扫全部历史
#
# 判定口径和线上完全一致：finder xml -> 整页 OCR -> band/胶囊档 -> in_region -> 退 COORD_。两处抄不到，必须说清：
#   1. 线上有 FIND_RETRY 重试，replay 只跑一轮。「认不到」只说明这一帧不行，不等于
#      线上那 8 轮也不行。
#   2. OCR 的中间结果（TSV）没留在证据里，所以 --ocr 是拿存下来的 PNG 重跑 tesseract，
#      不是重放当初那次识别的输出。

REPLAY_LOG=                   # run.log 里的 [STEP] 行：key<TAB>方式<TAB>x y<TAB>标签<TAB>分数
REPLAY_KEY=                   # --label 指定的 key
REPLAY_OVERRIDE=              # --label 指定的标签，'|' 分隔，和 ALIAS_ 同格式
REPLAY_REGION=ok              # replay_pick 时区域闸门有没有真的跑
SCALE_ARGS=()                 # 和 png_scale 共用，OCR 分支要填
TAP_W=0 TAP_H=0               # 点空间；回放没人调 wm size，从 run.log 抠或者 --size 给

replay_size_hint() {          # $1 = run.log，抠出 log RUN 那行的 720x1280
  local log=$1 dims
  [ -f "$log" ] || return 1
  # 不匹配中文，只认「3-4 位数字 x 3-4 位数字」这个形状；run.log 里只有点空间这一处
  dims=$(grep -oE '[0-9]{3,4}x[0-9]{3,4}' "$log" | head -1) || return 1
  [ -n "$dims" ] || return 1
  TAP_W=${dims%x*}
  TAP_H=${dims#*x}
  case ${TAP_W}${TAP_H} in *[!0-9]*|'') TAP_W=0 TAP_H=0; return 1;; esac
  [ "$TAP_W" -gt 0 ] 2>/dev/null && [ "$TAP_H" -gt 0 ] 2>/dev/null
}

replay_log_index() {          # $1 = run.log -> REPLAY_LOG
  REPLAY_LOG=
  [ -f "$1" ] || return 1
  REPLAY_LOG=$(sed -n 's/.*\[STEP\] \([A-Za-z_][A-Za-z_0-9]*\) 用 \([a-z]*\) 点 \([0-9]\{1,\}\) \([0-9]\{1,\}\) \[\(.*\) 分数=\([0-9]\{1,\}\)\].*/\1\t\2\t\3 \4\t\5\t\6/p' "$1")
  [ -n "$REPLAY_LOG" ]
}

replay_labels_of() {          # 和 labels_of 同义，但 --label 会顶掉 ALIAS_$1
  if [ -n "$REPLAY_KEY" ] && [ "$1" = "$REPLAY_KEY" ]; then
    [ -n "$REPLAY_OVERRIDE" ] || return 1
    printf '%s\n' "$REPLAY_OVERRIDE" | tr '|' '\n' | sed '/^[[:space:]]*$/d'
    return 0
  fi
  labels_of "$1"
}

replay_keys() {               # 配置里出现过的所有 key（ALIAS_ / COORD_ 都算）
  compgen -v | grep -E '^(ALIAS|COORD)_' | sed 's/^[A-Z][A-Z]*_//' | sort -u
}

replay_scale() {              # $1 = png -> 填 SCALE_ARGS（截图分辨率 -> 点空间）
  local dims d w h
  SCALE_ARGS=()
  dims=$(finder size "$1") || return 1
  d=($dims); w=${d[0]:-0}; h=${d[1]:-0}
  [ "$w" -gt 0 ] 2>/dev/null || return 1
  [ "${TAP_W:-0}" -gt 0 ] 2>/dev/null || return 1
  SCALE_ARGS=(--scale "$(awk -v a="$TAP_W" -v b="$w" 'BEGIN{printf "%.5f", a/b}')" \
                       "$(awk -v a="$TAP_H" -v b="$h" 'BEGIN{printf "%.5f", a/b}')")
}

replay_pick() {               # 同 pick，但点空间未知时跳过区域闸门并把结果标成 ?
  local key=$1 xy value score
  PICK_XY= PICK_LABEL= PICK_SCORE=0 REPLAY_REGION=ok
  if ! { [ "${TAP_W:-0}" -gt 0 ] && [ "${TAP_H:-0}" -gt 0 ]; } 2>/dev/null; then
    REPLAY_REGION=?
  fi
  while IFS=$'\t' read -r xy value score; do
    [ -n "$xy" ] || continue
    [ "$REPLAY_REGION" = ? ] || in_region "$key" "$xy" || continue
    PICK_XY=$xy PICK_LABEL=$value PICK_SCORE=$score
    return 0
  done
  return 1
}

replay_try() {                # $1=key $2=证据 stem（同名 .xml/.png）$3=要不要跑 OCR(0/1)
                              # -> 打印「判定<TAB>x y<TAB>标签<TAB>分数」
  local key=$1 stem=$2 want_ocr=$3 ovv ov psm cv coord
  ovv="OVERLAP_$key"; ov=${!ovv:-$MIN_OVERLAP}
  local -a labels=()
  while IFS= read -r l; do labels+=("$l"); done < <(replay_labels_of "$key")
  if [ ${#labels[@]} -eq 0 ]; then
    cv="COORD_$key"; coord=${!cv:-}
    if [ -n "$coord" ]; then
      printf 'coord\t%s\t固定比例\t0\n' "$(frac_xy "$coord" 2>/dev/null || printf '?')"
      return 0
    fi
    printf 'noalias\t\t\t\n'; return 1
  fi
  if [ -s "$stem.xml" ] \
     && finder xml "$stem.xml" "$ov" "${labels[@]}" >"$TMP/replay-hits.txt" 2>/dev/null \
     && replay_pick "$key" <"$TMP/replay-hits.txt"; then
    printf 'hit\t%s\t%s\t%s\n' "$PICK_XY" "$PICK_LABEL" "$PICK_SCORE"; return 0
  fi
  if [ "$want_ocr" = 1 ] && [ -s "$stem.png" ] && [ -n "${OCR_LANG:-}" ] && have tesseract \
     && replay_scale "$stem.png"; then
    for psm in $OCR_PSM $OCR_PSM_PAGE; do
      tesseract "$stem.png" stdout -l "$OCR_LANG" --psm "$psm" tsv \
        >"$TMP/replay-$psm.tsv" 2>/dev/null || continue
      [ -s "$TMP/replay-$psm.tsv" ] || continue
      if finder "${SCALE_ARGS[@]}" --min-conf "$OCR_MINCONF" tsv "$TMP/replay-$psm.tsv" "$ov" \
           "${labels[@]}" >"$TMP/replay-hits.txt" 2>/dev/null \
         && replay_pick "$key" <"$TMP/replay-hits.txt"; then
        printf 'ocr\t%s\t%s\t%s\n' "$PICK_XY" "$PICK_LABEL" "$PICK_SCORE"; return 0
      fi
    done
  fi
  # 线上在整页 OCR 之后还有 band 档（裁一条再 OCR），胶囊档挂在它后面。这一段不补，
  # replay 的口径就和线上不一致，反色那两档在这儿永远验不到。
  if [ "$want_ocr" = 1 ] && [ -s "$stem.png" ] && [ -n "${OCR_LANG:-}" ] \
     && have tesseract && [ "${TAP_W:-0}" -gt 0 ] 2>/dev/null; then
    if band_pass "$key" "$stem.png" && replay_pick "$key" <"$TMP/band-hits.txt"; then
      printf 'band\t%s\t%s\t%s\n' "$PICK_XY" "$PICK_LABEL" "$PICK_SCORE"; return 0
    fi
  fi
  cv="COORD_$key"; coord=${!cv:-}
  if [ -n "$coord" ]; then
    printf 'coord\t%s\t配置兜底\t0\n' "$(frac_xy "$coord" 2>/dev/null || printf '?')"
    return 0
  fi
  printf 'miss\t\t\t\n'; return 1
}

replay_nearest() {            # $1=key $2=线上方式（'-' 表示不限）$3=xy（给 '-' 表示只看有没有）
                              # -> 「方式|x y|标签|分数<TAB>距离平方」
  local key=$1 want=$2 xy=$3 k lm lxy lab sc ax ay d axa aya best= bestd=99999999
  local -a wx wy
  if [ "$xy" != '-' ]; then
    wx=(${xy% *}); wy=(${xy#* })
    [ -n "${wx[0]:-}" ] && [ -n "${wy[0]:-}" ] || return 1
  fi
  while IFS=$'\t' read -r k lm lxy lab sc; do
    [ -n "$k" ] || continue
    [ "$k" = "$key" ] || continue
    [ "$want" = - ] || [ "$lm" = "$want" ] || continue
    if [ "$xy" = '-' ]; then
      printf '%s|%s|%s|%s\t0\n' "$lm" "$lxy" "$lab" "$sc"
      return 0
    fi
    axa=(${lxy% *}); aya=(${lxy#* })
    ax=${axa[0]:-0}; ay=${aya[0]:-0}
    d=$(( (ax - wx[0]) * (ax - wx[0]) + (ay - wy[0]) * (ay - wy[0]) ))
    if [ "$d" -lt "$bestd" ]; then bestd=$d; best="$lm|$lxy|$lab|$sc"; fi
  done <<<"$REPLAY_LOG"
  [ -n "$best" ] || return 1
  printf '%s\t%s\n' "$best" "$bestd"
}

replay_frame() {              # $1=证据 stem  $2=帧里带的 key  $3=要试的 key  $4=要不要 OCR
  local stem=$1 fkey=$2 tkey=$3 want_ocr=$4 out method xy lab sc near prev verdict m
  out=$(replay_try "$tkey" "$stem" "$want_ocr")
  IFS=$'\t' read -r method xy lab sc <<<"$out"
  [ "$method" = noalias ] && method=miss
  case $method in
    # 认到字的三条路一视同仁。10-20 之前这里漏了 band：胶囊档和 band 档明明认到了字，
    # 却被归到下面「既认不到字又没有兜底」那一档，重放表把修复读成了没修复。
    hit|ocr|band)
      m=$method; [ "$m" = hit ] && m=xml
      if near=$(replay_nearest "$tkey" "$m" "$xy" 2>/dev/null); then
        prev=${near%$'\t'*}; verdict=${near##*$'\t'}
        if [ "$verdict" -le 8 ] 2>/dev/null; then verdict=一致; else verdict=变了; fi
      elif near=$(replay_nearest "$tkey" - "$xy" 2>/dev/null); then
        prev=${near%%$'\t'*}; verdict=方式变了
      else
        prev='-'; verdict=无记录
      fi ;;
    coord) # 今天认不到字、只能退坐标兜底。点空间不知道时比例没法换算成像素，
           # 这时候只报「有没有兜底」，不比对位置。
           if [ "$xy" = '?' ]; then
             prev='-'; verdict='有比例兜底(点空间未知)'
           elif near=$(replay_nearest "$tkey" coord "$xy" 2>/dev/null); then
             prev=${near%%$'\t'*}; verdict='一致(靠坐标)'
           elif near=$(replay_nearest "$tkey" - "$xy" 2>/dev/null); then
             prev=${near%%$'\t'*}; verdict=降级到坐标
           else
             prev='-'; verdict=无记录
           fi ;;
    *)   # 今天既认不到字、这个 key 又没有 COORD_ 兜底 -> 这一步线上会直接 FAIL。
         # 这是最该盯的一类：当初靠字点进去的，现在没得点了。
         if near=$(replay_nearest "$tkey" - '-' 2>/dev/null); then
           prev=${near%%$'\t'*}
           case ${prev%%|*} in
             coord) verdict='一致(无COORD,当初是坐标?)' ;;
             *)     verdict='认不到且无兜底' ;;
           esac
         else
           prev='-'; verdict='认不到且无兜底'
         fi ;;
  esac
  printf '%-24s %-9s %-6s %-11s %-16s %-3s | %-26s %s\n' \
    "${stem##*/}" "$tkey" "$method" "${xy:--}" "${lab:--}" "${sc:--}" "$prev" "$verdict"
  printf '%s\t%s\n' "$tkey" "$method" >>"$TMP/replay-sum.tsv"
}

replay_frames() {             # $1=目录 -> 每行「证据 stem<TAB>帧里的 key」
  local dir=$1 f base stem key att rest ext known
  local -A seen=()
  known=" $(replay_keys | tr '\n' ' ') "
  # xml 和 png 都要扫：这一轮跑完常常只留下截图（uiautomator 有时 dump 不出来），
  # 只认 xml 的话 --ocr 就一帧都枚举不到。同一个 stem 出一次就够，replay_try 自己会两样都找。
  for ext in xml png; do
    for f in "$dir"/*.$ext; do
      [ -f "$f" ] || continue
      base=${f##*/}; base=${base%.$ext}
      # 证据名 = <秒数>-<key>-<第几轮>；轮次从右往左剥，中间那段是 key。
      # probe.* 和 count-* 不参与：前者不是某一步的证据，后者不带 key。
      case $base in
        *-*-*) ;;
        *) continue ;;
      esac
      att=${base##*-}
      rest=${base%-*}
      key=${rest#*-}
      [ -n "$key" ] || continue
      case $known in *" $key "*) ;; *) continue ;; esac
      stem="${dir}/${base}"
      [ -n "${seen[$stem]:-}" ] && continue
      seen[$stem]=1
      printf '%s\t%s\n' "$stem" "$key"
    done
  done
}

cmd_replay() {
  local dir= size= scan= want_ocr= key r stem fkey tkey av cvv
  while [ $# -gt 0 ]; do
    case $1 in
      --all)  shift
              if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then dir=$1; shift; fi ;;
      --size) shift; size=${1:-}
              case $size in
                *x*) ;;
                *) printf 'replay: --size 要 WxH\n' >&2; return 2 ;;
              esac
              shift ;;
      --scan) shift; scan=1 ;;
      --ocr)  shift; want_ocr=1 ;;
      --label)
              shift
              key=${1:-}
              [ -n "$key" ] || { printf 'replay: --label 后面要 key\n' >&2; return 2; }
              shift
              REPLAY_OVERRIDE=${1:-}
              [ -n "$REPLAY_OVERRIDE" ] || { printf 'replay: --label %s 后面至少要一个标签\n' "$key" >&2; return 2; }
              shift
              while [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; do
                REPLAY_OVERRIDE=$REPLAY_OVERRIDE\|$1
                shift
              done
              REPLAY_KEY=$key ;;
      -*)    printf 'replay: 不认得 %s\n' "$1" >&2; return 2 ;;
      *)     dir=$1; shift ;;
    esac
  done
  if [ -n "$REPLAY_KEY" ]; then
    av="ALIAS_$REPLAY_KEY"; cvv="COORD_$REPLAY_KEY"
    [ -n "${!av:-}${!cvv:-}" ] || { printf 'replay: 配置里没有 key「%s」\n' "$REPLAY_KEY" >&2; return 2; }
  fi
  [ -n "$dir" ] || dir=$EVIDENCE_DIR
  [ -d "$dir" ] || { printf 'replay: 没有这个目录 %s\n' "$dir" >&2; return 2; }
  local -a runs=()
  if [ -f "$dir/run.log" ]; then
    runs=("$dir")
  else
    while IFS= read -r d; do [ -n "$d" ] && runs+=("$d"); done \
      < <(find "$dir" -mindepth 2 -maxdepth 2 -type d 2>/dev/null | sort)
  fi
  [ ${#runs[@]} -gt 0 ] || { printf 'replay: %s 下面没有 <日期>/<时间>/ 这样的运行目录\n' "$dir" >&2; return 2; }

  if [ -n "$size" ]; then TAP_W=${size%x*}; TAP_H=${size#*x}; fi
  [ "${TAP_W:-0}" -gt 0 ] 2>/dev/null || replay_size_hint "${runs[0]}/run.log"

  printf '回放 %s\n' "$dir"
  if [ "${TAP_W:-0}" -gt 0 ] 2>/dev/null; then
    printf '点空间 %sx%s，区域闸门生效\n' "$TAP_W" "$TAP_H"
  else
    printf '点空间 未知，区域闸门跳过，只按文字判定（--size 720x1280 可以补上）\n'
  fi
  [ -n "$REPLAY_KEY" ] && printf '标签覆盖 %s <- %s\n' "$REPLAY_KEY" "$REPLAY_OVERRIDE"
  [ -n "$scan" ] && printf '扫描模式：每帧都试所有 key\n'
  if [ "$want_ocr" = 1 ] && ! have tesseract; then
    printf '没装 tesseract，--ocr 这一段跳过\n'
  fi
  printf '帧 = 证据文件名，判定 = 今天配置会怎么点，当初 = run.log 里那次实际怎么点的\n\n'
  printf '%-24s %-9s %-6s %-11s %-16s %-3s | %-26s %s\n' \
    帧 key 判定 坐标 标签 分 当初 结果

  : >"$TMP/replay-sum.tsv"
  for r in "${runs[@]}"; do
    replay_log_index "$r/run.log"
    printf '\n=== %s\n' "${r#"$EVIDENCE_DIR"/}"
    replay_frames "$r" | while IFS=$'\t' read -r stem fkey; do
      if [ -z "$scan" ]; then
        replay_frame "$stem" "$fkey" "$fkey" "$want_ocr"
      else
        while IFS= read -r tkey; do
          [ -n "$tkey" ] || continue
          replay_frame "$stem" "$fkey" "$tkey" "$want_ocr"
        done < <(replay_keys)
      fi
    done
  done

  printf '\n汇总（每帧 × 每个试过的 key）\n'
  # band 档必须单独数出来：10-20 修好了逐帧那行（replay_frame 里 hit|ocr|band 一视同仁），
  # 这行总数漏了 band，于是一批帧里 8 帧走裁片只报 4 帧 —— 又是"把修复读成没修复"。
  awk -F'\t' '{ c[$1"|"$2]++; if (!($1 in seen)) { seen[$1]=1; ord[++n]=$1 } }
    END { for (i=1;i<=n;i++) { x=ord[i]
            printf "  %-10s 认到字 %d / 走 OCR %d / 走裁片 band %d / 退坐标 %d / 认不到 %d\n",
                   x, c[x"|hit"], c[x"|ocr"], c[x"|band"], c[x"|coord"], c[x"|miss"] } }' \
    "$TMP/replay-sum.tsv"
  printf '\n三处别误读：\n'
  printf '  退坐标那几帧最脆 —— 坐标是照着一版版面量下来的，版面一跳就点到别的东西上（10-16 那晚点到的是百事可乐那张贴），verify_light 对纯坐标那一枪本来就是判失败的。\n'
  printf '  「认不到」只说明这一帧不行；线上还有 FIND_RETRY 会继续等，别据此就改配置。\n'
  printf '  要验 OCR 加 --ocr，那是拿存下来的 PNG 重跑 tesseract，不是重放当初的输出。\n'
  return 0
}
cmd_status() {
  printf '设备      %s (%s)\n' "$DEVICE" "$(device_online && echo 在线 || echo 离线)"
  printf 'OCR       %s\n' "$(have tesseract && tesseract --version 2>&1 | head -1 || echo 没装：只剩 XML 和固定坐标)"
  printf '步骤      %s\n' "$STEPS"
  printf '今天      %s (%s)\n' "$(marker_path)" "$([ -f "$(marker_path)" ] && echo 已完成 || echo 未完成)"
  printf '兑换倒数  %s\n' "$(
    d=$(ledger_read) || d=
    if [ -z "$d" ]; then echo "$PAUSE_FILE 没有或不是数字（不挡路，只当没记过）"
    elif [ "$d" = 0 ]; then echo "0：现在不在待兑换期，每天照常点亮"
    else echo "$d 天后可兑换（只是账本，不挡路，这几天每天照常碰手机）"
    fi
  )"
  printf '推送      %s\n' "$(
    if [ -z "$PUSH_URL" ]; then
      echo "没配端点（环境变量没给，$PUSH_URL_FILE 也读不到），一条都不推，流程照跑"
    else
      echo "端点已配置（来自 $PUSH_URL_SRC，长度 ${#PUSH_URL}；地址本身带 token，不打印）"
    fi
  )"
  printf '证据      %s\n' "$EVIDENCE_DIR"
  ls -1dt "$EVIDENCE_DIR"/*/*/ 2>/dev/null | head -3
}

case ${1:-run} in
  run)    shift; cmd_run "${1:-}"; exit $? ;;
  probe)  cmd_probe; exit $? ;;
  find)   shift; cmd_find "$@"; exit $? ;;
  point)  shift; ensure_device && adb_shell input tap "$1" "$2"; exit $? ;;
  shot)   ensure_device && mkdir -p "$RUN_DIR" && grab_shot "$RUN_DIR/shot.png" && echo "$RUN_DIR/shot.png"; exit $? ;;
  status) cmd_status; exit $? ;;
  replay) shift; cmd_replay "$@"; exit $? ;;
  *)      printf '用法: %s [run [force]|probe|find <key>|point <x> <y>|shot|status|replay <证据目录>]\n' "${0##*/}" ;;
esac
