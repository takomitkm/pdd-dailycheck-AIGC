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

## 4. 其他真机事实

- `uiautomator dump /dev/tty` 在本机返回 0 字符 → 必须 dump 到文件再 cat（已修）
- 频道页 XML 只有 3.5KB（WebView/Canvas 渲染）→ **XML 通道在频道页基本无效**，只能靠 OCR
- 真机耗时：全页 OCR psm6 p50 2.29s、psm11 2.16s；跳过 XML 单帧 2.28s vs 取 XML 5.45s
- 真实 launcher activity：`com.xunmeng.pinduoduo/.ui.activity.MainFrameActivity`
  （与旧脚本 HOME_ACT 一致；启动后自己跳到 HomeActivity）
