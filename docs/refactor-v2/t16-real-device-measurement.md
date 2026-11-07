# T16 真机测量附记（部署目标 deb-h61，2026-11-07 11:0x）

> 方法：h61 上以 staging 站点跑 `scripts/dryrun_h61.py`，真实 AdbDevice + TesseractEngine，
> **动作执行器被 DryRunDevice 全量拒绝（零副作用）**。手机 `192.168.1.110:16132`。

## 单帧成本（720×1280 真机桌面，psm6）

| 配置 | observe 耗时 | 取数 |
|---|---|---|
| 重复截图 + 取 XML | 6033 ms | 2×screencap + xml + ocr |
| 复用预取帧 + 取 XML | **5372 ms** | 1×screencap + xml + ocr |
| 复用预取帧 + **跳过 XML** | **2277 ms** | 1×screencap + ocr |

- 复用帧：省 ~0.66s（实测与预测一致）。
- **跳过 XML：省 ~3.2s，帧成本几乎减半**——XML dump 在真机约 3.2s，是最大单项。
- 拆项：connect 10ms；screencap 654ms；locate 8ms；OCR(psm6 全页) ~2.2s。
- 结论：T16 的优化优先级应为 **①按页跳过/惰性 XML（-3.2s） ②帧复用（-0.66s） ③同帧多目标共享（已实现，省重复 OCR/截图）**；单次全页 OCR ~2.2s 是硬底，换后端或裁片才可能再降。

## 安全性发现（重要）

干跑时 `bag` 在**桌面**上用坐标兜底「命中」了 (100,895)——因为桌面没有「抽福袋」文本。
这正说明：**坐标兜底必须在正确页面上才允许**。新合同的 `ActionIntent` 校验（business
动作必须带 expected_package=pdd + required_window_kind=APP + source_candidate_id）
会在真实执行路径挡住它（桌面前台不是 pdd，intent 被拒）。但这也提醒：任何「真机实跑」
不能绕过 intent 校验直接用裸坐标。**本轮据此没有执行任何真实业务动作。**

## 真机 OCR 复核

h61 对同一真图：psm6 p50 **2.29s**、psm11 p50 **2.16s**（3 次）。与上方 observe 拆项一致。
