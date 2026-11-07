# 真机标定发现（2026-11-07，h61 + 手机 192.168.1.110:16132）

> 这些是**真机实测**得到的数据，与冻结 profile 的差异需要按 D08 走批准，不擅自改标定。

## 1. 首页入口「百亿补贴」= 艺术字图片，OCR 认不出，坐标是唯一手段

- 真机首页 XML（81KB）**没有**「百亿补贴」节点（只有 限时秒杀/充值中心/免费领礼物/9块9特卖/点我领券…）
- 整页 psm6+psm11 OCR 也读不出「百亿补贴」（艺术字）
- 但 `COORD_subsidy=0.125,0.46875` → **(90,600)** 手动点击后前台变为
  `com.xunmeng.pinduoduo.activity.NewPageActivity` ✓ —— **旧脚本的坐标标定仍然有效**
- 我们的流程段因此加入坐标兜底（护栏：AdbDevice 校验前台必须是 pdd），实测 `entry:ok`

## 2. 频道页「抽福袋」胶囊：整页 OCR 与 band 档都不够，必须用 pill 档（color ×2 psm7）

真机实测（同一帧 720×1280）：

| 配方 | 结果 |
|---|---|
| 整页 psm6 / psm11 | 读出「百亿补贴品质保障」「抢低至5折」，**没有「抽福袋」** |
| band（region 0,0.35,1,0.85 + 灰度 + autocontrast + ×3, psm7） | 113 字符噪声，**没有「抽福袋」** |
| 紧裁 (370,495,505,550) color ×3 | `Hite`（废） |
| 紧裁 同上 inv ×3 | 空 |
| **宽裁 (340,480,540,560) color ×2 psm7** | **`抽` `福` `袋` 三词同一行 → 合成「抽福袋」conf 92.6** |

用我们自己的定位器跑这份 TSV（pill 通道几何：scale=tap/img/2 的 5 位小数、offset=裁片原点回推）：

```
lines: [('抽福袋', 92.6)]
candidates: [((435, 524), 3)]        ← 与旧脚本 10-18 实测 (435,524) 逐位一致
```

## 3. 需要的标定决定（D08，待批准）

现有 profile `targets.bag.pill = [0.02, 0.64, 0.32, 0.78]` 是**活动页**那颗胶囊；
**频道页**这颗在 `约 [0.472, 0.375, 0.75, 0.4375]`（color 模式，×2，psm7）。两个方案：

- **A（推荐）**：给 TargetSpec 增加第二个胶囊框（如 `pill_channel`），流程按当前页型选用。
  需要 schema 扩展（向后兼容：缺省=不启用），属合同变更，要 ADR。
- **B**：把频道页这颗作为**新目标键**（如 `bag_channel`）加入 profile 与流程段。
  不改 schema，但流程段要知道「在频道页用 bag_channel、在活动页用 bag」。

两者都不改变识别算法，只补标定。**未批准前不动冻结 profile**，演练脚本里用显式参数试验证。

## 5. 流程闭环的剩余问题（2026-07 11:40 真机连跑记录）

真机连跑（`rehearse_real.py`，0.1.11→0.1.15）逐版实测，已解决与未解决：

**已解决**
1. 入口坐标 (90,600) → 进频道页 ✓（`entry:ok` 多次复现）
2. 频道页「抽福袋」pill color×2 psm7 → 候选 **(435,524)** ✓（4 帧一致）
3. 手动点 (435,524) → **确实进入消费券活动页**，页面上有「9天内再点亮5次必得」「今日已点亮」
4. `facts_from_text("9天内再点亮5次必得 今日已点亮")` → `count=5, done=今日已点亮` ✓

**未解决（下一轮）**
5. **活动页与频道页是同一个 `NewPageActivity`**：不能用 activity 判「已进福袋页」，
   必须用页面文字（进度行/done/pend）——已改成文字判据。
6. **盲目 BACK 会形成死循环**：点进活动页后若证明失败又发 BACK，会退回频道页，
   再点再退（真机连跑 p5 就是这个循环）。已改：点后不 BACK，只重新观察。
7. **连跑时页面状态漂移**：上一轮留下的页面（活动页/频道页/首页）影响下一轮的起点，
   导致 rc4/rc5 交替出现。→ 下一轮先加「确定性起点」：显式 `start` + 校验前台是
   首页（HomeActivity）再开始，避免继承残留状态。
8. 演练脚本的 receipt 记录只在 executed 时写，dry 分级下看不到「点了但被拦」——
   已在 p5 后补（本轮的 tap 确实执行了，见 points (435,524)×3）。

## 6. 真机全链路已跑通（2026-11-07 11:52，v0.1.18）

```
stages: ["ready:ok", "entry:ok", "bag:ok", "facts:read"]     pages=6
receipts: tap acknowledged ×2（护栏校验通过）
页面文字: 「拼多多首页 点百亿补贴 参与活动 … 9天内再点亮5次必得 … 共100元券」
facts: progress=5
```

**这轮修掉的编排 bug（都是真机才暴露的）**
1. 确定性起点：`ensure_ready` 现在会 `start` → 校验 pdd → 不在首页则 BACK ≤3 次回首页（rc7 收手）
2. activity 判据误用：活动页/频道页同为 `NewPageActivity` → 改**页面文字**判据
3. BACK 死循环：点后证明失败又 BACK → 退回频道页再点（p5 循环）→ 点后不 BACK
4. 裁片候选优先：整页会把零散「抽/福/袋」误配成「抽福袋」（曾点错到 (200,20)）
5. 有裁片供给器时禁用整页坐标兜底（bag COORD 是活动页那颗的位置）
6. 演练开关语义冲突：`--execute-lifecycle` 与 `--execute-entry-tap` 同时给时 tap 全被拦
   （p7 的 executed:false）→ entry-tap 优先
7. `ActionIntent` 业务动作必须带 expected_package + required_window_kind（SWIPE 也算业务）

**遗留**
- `done` 读不到：活动页「今日已点亮」按钮不在整页 OCR 文本里（真图确认在进度条右侧，
  属 pill 档/裁片范围）。需给 `done` 配 pill 框（现有 profile 已有
  `done.pill = [0.597, 0.184, 1.0, 0.270]`，但演练只接了 bag 的 pill）→ 下轮把
  多目标 pill 通道接上。



## 7. done/light 裁片配方真机验证（2026-11-07 12:0x）

**现有 profile 的 `done.pill = [0.597, 0.184, 1.0, 0.270]`（inv ×2 psm7）真机可用**：

```
裁片 (429,235)-(720,345)，inv + 硬阈值 120 + ×2，psm7
读出: 「今日已点之」conf 96.1（「亮」误识为「之」，不影响匹配）
匹配: 「已点亮」连续段 4 字命中，候选点 (600,290)
```

→ **不需要改 done 标定**，现有值正确。同理 light/exchange 共用该框。

**但发现页型耦合**：bag 的 pill 框只在**频道页**有效、done 的 pill 框只在**活动页**有效。
把多目标 pill 一起无脑跑，会在错误页型上产出空候选（本轮 p10 实测：起点在首页时
bag/done/light 全部 candidates=[]）。→ 必须**按页型选通道**（ADR-003 的 `pill_channel`
设计正是为此），而不是全跑。


- `uiautomator dump /dev/tty` 在本机返回 0 字符 → 必须 dump 到文件再 cat（已修）
- 频道页 XML 只有 3.5KB（WebView/Canvas 渲染）→ **XML 通道在频道页基本无效**，只能靠 OCR
- 真机耗时：全页 OCR psm6 p50 2.29s、psm11 2.16s；跳过 XML 单帧 2.28s vs 取 XML 5.45s
- 真实 launcher activity：`com.xunmeng.pinduoduo/.ui.activity.MainFrameActivity`
  （与旧脚本 HOME_ACT 一致；启动后自己跳到 HomeActivity）
