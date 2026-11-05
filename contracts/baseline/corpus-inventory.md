# 真图语料清单（corpus-inventory）

目的：重构的质量门禁（acceptance.md §8）需要**固定真实帧**做 ground truth。本文件记录
2026-11-06 时点真实可得的数据，防止把「文本转记」当「原图」、把「7 天滚动窗口」当「固定语料」。

## 仓库内（已核实，glob 全量）

| 类型 | 数量 | 说明 |
|---|---|---|
| 原始 PNG / XML / run.log | **0** | 仓库不带任何真机证据帧 |
| 文本转记 | docs/measurements/*.txt（measured-RESULTS、measured-RESULTS2-upscale、measured-FRAMES-two-nights、measured-AB-1102-routes） | 是当时人工/脚本抄录的**识别字符串与结论**，不是图片；不能当 OCR ground truth 或 Q 门禁数据集 |

## 主机端（未采集，需授权/自然机会）

| 数据 | 位置 | 状态 |
|---|---|---|
| 7 天滚动证据窗 | deb-h61 `~/Desktop/pdd-runs/<日期>/<场次>/`（PNG + XML + run.log；README 载 9 份 run.log 口径） | **未采集**。KEEP_DAYS=7 会滚动删除，必须先复制到固定语料目录才能当数据集 |
| 历史更早帧 | 已被 7 天窗口删除 | 不可恢复 |
| 真机新采集 | 手机 192.168.1.110:16132 | 需用户授权；且受「每天一次真实机会」约束，不能为凑数据集烧福袋/兑换 |

## 结论与缺口（对 acceptance §8 的影响）

1. **T04 当前无法开始真图标注**——没有一张原图可标。G1b 的 dataset manifest 只能先立 schema 与
   采集规程，coverage gap 记「全部真图类缺失」。
2. 采集优先级（自然机会顺带收集，不额外跑手机）：每日 run 的证据目录在 KEEP_DAYS 删除前
   复制出库 → 按 HOME/CHANNEL/ACTIVITY(done/used/exchange/pend)/BROWSE/PRIZE/UNKNOWN 分桶。
3. 目标（每类 ≥5 张、≥3 个日期）在若干个自然日后才可能凑齐；期间 Q 门禁只能以
   合成 resize（几何性质）+ 桩沙箱（分支契约）运行，**不得冒充真图质量结论**。
4. 涉及账号昵称/券面额的帧属于私有语料：入库前脱敏，脱敏后重验涉及 ROI 的识别结果。
