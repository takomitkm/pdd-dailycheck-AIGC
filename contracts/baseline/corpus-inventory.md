# 真图语料清单（corpus-inventory）

目的：重构的质量门禁（acceptance.md §8）需要**固定真实帧**做 ground truth。本文件记录
语料的采集状态与覆盖。

## 采集状态：已回收（2026-11-06 07:45，用户授权）

- **来源一：deb-h61 的 7 天证据窗整包回收**（12 场，2026-10-29 → 11-06；再晚一天 10-29 场就会被
  KEEP_DAYS 删掉）。358 张 PNG + 150 个 XML + run.log/summary，共 98MB。
- **来源二：真机只读截图 ×2**（07:43/07:43:54，`pdd.sh shot`，无任何点击）——拍到的是
  **桌面 launcher 态**（亮屏未锁，720×1280）：真机当前状态凭证 + HOME-launcher 类帧。
- **存放**：仓库外私有目录 `S:\apps\llm\agentwork\pdd-corpus-private\pdd-runs\`
  （原图含账号昵称/券面额，**永不入 git**）。
- **索引**：[tests/fixtures/manifest/corpus-v1-index.json](../../tests/fixtures/manifest/corpus-v1-index.json)
  （544 文件逐个 SHA256+类别+会话，只含路径/哈希，不含像素）；生成器
  `build_corpus_index.py`，私有目录变动后重跑即可。

### 类别分布（按证据文件名的 key）

| 类别 | 张数 | 说明 |
|---|---|---|
| bag | 60 | 频道页/轮播帧，含左右两个版式 |
| popup | 30 | 弹窗帧 |
| pend | 15 | 待兑换终态 |
| done | 13 | 已点亮/已使用终态 |
| browse | 6 | 浏览横幅帧 |
| light | **3** | 点亮胶囊帧——**低于每类 ≥5 目标，缺口记账** |
| png-other | 231 | band/pill 裁片与杂项 PNG（非整页帧，标注时单列） |
| hierarchy-xml | 150 | uiautomator 层级 |
| run-log / summary / other | 10/10/16 | 会话元数据 |

## 结论与缺口（对 acceptance §8 的影响）

1. **T04 标注可以开始了**：bag/popup/pend/done/browse 五类已够每类 ≥5 张的起步目标；
   **light 只有 3 张**——下一批自然机会（每天 10:00 的 run 会产生新 light 帧）顺带补齐，
   不为凑数额外跑手机。
2. xml 与 png 同场配对存在 → 快照级（图+层级+焦点推断）样本可用。
3. 涉及昵称/券面额：标注在私有目录进行；公开仓库只入索引与脱敏结论。
4. 切分（calibration/heldout）按场次/日期分组，等标注完成后执行（T04 后续）。
5. 历史更早帧（10-29 之前）已被 7 天窗口删除，不可恢复——此批即历史存量上限。
