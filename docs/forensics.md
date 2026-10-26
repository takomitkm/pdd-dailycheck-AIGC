# 失败取证：跑完之后怎么查

## 一次跑留下什么

证据目录 `$HOME/Desktop/pdd-runs/<日期>/<时分秒>/`，保留 `KEEP_DAYS=7` 天：

| 文件 | 是什么 |
| --- | --- |
| `run.log` | 全程日志，每条都带时间戳和级别（RUN/FAIL/DONE/WARN/PROBE） |
| `summary.txt` | 收条：`result` / `lit` / `steps` / `date` / `evidence` / `screen` / `why` |
| `probe.xml`、`probe.png` | `pdd.sh probe` 存的界面快照 |
| `<时刻>-<key>-<n>.png` | 每一步的帧，key 见桩文件名规则：`popup` / `bag` / `light` / `count` / `pend` / `done` / `prove` |
| `.done-<日期>` | 今天完成标记（在 `pdd-runs/` 根上，不在这场目录里） |

`why` 这个字段专门用来区分两种"没核实成功"：「进度没变」= 真没点着，
「读不到进度行」= 版面又变了或中奖后那行消失了。两种要做的事不一样。

## 排查顺序

```sh
ssh deb-h61 'journalctl --user -u pdd.service -n 80 --no-pager'      # 服务有没有被定时器拉起
ssh deb-h61 'ls -1t ~/Desktop/pdd-runs/ | head; cat ~/Desktop/pdd-runs/<日期>/<场次>/summary.txt'
ssh deb-h61 'tail -60 ~/Desktop/pdd-runs/<日期>/<场次>/run.log'
```

看日志里的定位来源就能分诊：出现 `coord` 说明前五档全空，出现 `没找到` 说明连兜底都没有，
出现 `下滑 i/20` 但进度没变通常是横幅认不到（去看 `*browse*.png`）。

## 只读取证脚本（都不碰手机）

| 脚本 | 用法 | 干什么 |
| --- | --- | --- |
| `tools/tsvdump.sh` | `tsvdump.sh <帧.png>` | 整页 psm 11，列出所有带字的行及其**中心坐标**（按 720x1280 点空间） |
| `tools/read_evi.sh` | `read_evi.sh <证据目录>` | 把那场所有 PNG 逐张整页 OCR，看卡在哪个画面 |
| `tools/browseprobe.sh` | `browseprobe.sh <帧.png>` | 复现 browse 的各通道读数：整页 psm11 / psm6 / band 档 |
| `tools/bannersweep.sh` | `bannersweep.sh <帧.png>` | 横幅窄条的预处理扫描，找哪一档能读出那句「滑动浏览…即可点亮」 |
| `tools/bandcmp.sh` | `bandcmp.sh <帧.png>` | 同一帧试两种 band 裁片：现状 `REGION_browse` vs 收紧到横幅那一条 |
| `tools/band6tsv.sh` | `band6tsv.sh <帧.png>` | 在 band 档真裁片上跑 psm 6/7/11 的 tsv，列出命中别名的行 |
| `tools/bagpos.sh` | `bagpos.sh <帧1.png> <帧2.png> …` | 跨帧比对「抽福袋」这类字都出现在哪些坐标（版面跳位就靠它量） |
| `tools/pend_tune.sh` | `pend_tune.sh <pend帧.png> …` | 离线调 pend 那档的天数读数，每个变体输出「变名 \| 整句 \| 抠出的 N \| 是否命中」 |
| `tools/cal_pend.sh` | 见文件头 | 把当天福袋页截图改名成 replay 认得的证据名，再拿新配置重打分 |

`tools/` 里这些要在**装了 tesseract 和 Pillow 的那台 Debian 上跑**，本机 Windows 没有 chi_sim。
把帧从 `pdd-runs` 里 scp 出来，或者直接在主机上跑都行。

## 配置改动先在 replay 上过一遍

```sh
~/Desktop/pdd.sh replay ~/Desktop/pdd-runs/2026-10-18/105503 --ocr
```

`replay` 不需要 adb、不需要连设备，判定口径和线上一致。它的两条限制写在
[calibration.md](calibration.md) 第四节，读结果时必须记住（尤其是"replay 只跑一轮"那条，
`FIND_RETRY_bag=12` 的轮播扫描它复现不了）。

**想拿一帧按别的 key 判定，得改文件名，不能只加 `--label`。** 判定用的 key 来自证据名
`<秒数>-<key>-<轮次>.png`，`--label <key> <词...>` 只覆盖那个 key 的 `ALIAS_`，
不会把别的帧拽过来判 —— 所以 `--label done ...` 配一批 `count-prove-bag` 帧，跑出来的是
`bag`/`pend` 那几个 key 的账，`done` 一行都不出。10-26 数误报面时的做法是把帧复制成
`<秒数>-done-1.png` 再放进展窗目录，这样区域闸门、`OCR_PSM_BAND_done` 那些档位走的都是线上同一套：

```sh
mkdir -p /tmp/batch/$(date +%F)/2231
cp <某帧>.png /tmp/batch/$(date +%F)/2231/101133-done-1.png
~/Desktop/pdd.sh replay /tmp/batch --ocr --size 720x1280      # 目录给到「日期」那一层
```

还有一条读法上的坑：汇总行在 10-26 之前只数 xml/ocr/coord/miss，**`band` 档不进总数**
（修在 [pdd.sh:1863](../pdd.sh#L1863)），所以一批靠裁片认到的帧会在汇总里"消失"，
把修复读成没修复；逐帧那行的 `band` 一直是对的，两处数字不一致时先怀疑汇总行那半。

## 两件已知的耗时与噪音

1. **bag 那一步在恢复路径上会白烧约 90 秒**：`FIND_RETRY_bag=12 × FIND_INTERVAL_bag=3`。
   这个位置是轮播，一帧「抽福袋」一帧「百亿消费券 100元券待领」，轮次给少了全是后一帧。
   一次完整跑实测约 9 分钟，所以服务的 `TimeoutStartSec=25min`。
2. **`find <key>` 超时会打印半截前缀**，形如 `bag  subsidy  coord 90 600`。
   那是 `find_target` 里未闭合的 printf 留下的，不是把 subsidy 的坐标当成 bag 认到了。
   要干净输出就分 key 单跑。

## 10-18 那天出过一次的事，留作案例

消费券页整页确实没有进度卡（BACK 之前原地读 99 秒全空），所以滑完立刻 BACK 回活动页；
频道页那颗胶囊现在认得到字（`(435,524)`，真机两次都从那儿进的活动页）。
但 `BROWSE_BACK=false` 这一档还是关着——BACK 已经挪到 `verify_light` 里无条件打了（滑完必按），
在这里再按一次会变成连退两页。改这一条之前先想清楚 BACK 的归属。
