# refactor-v2 合并审计报告（离线阶段）

> 生成：2026-11-07 · 分支 `refactor-v2` · 基线源 `pdd.sh` sha256 `8bd6e038…c760e90`（冻结，未改动）
> 本报告只汇总**已完成并可复核**的离线成果；真机/安装类事项明确标注「待授权」，不夸大。

## 1. 门禁证据（可复核）

| 门禁 | 证据 | 结果 |
|---|---|---|
| G0a 沙箱双分辨率 | `reports/harness-result.json`：720×1280 与 1440×2560 各 47/47，负对照 11 执行/11 杀死，4 个反例均按预期失败 | **pass** |
| 单测/集成 | `pytest tests` | **326 passed + 4 skipped**（POSIX 锁测试在 Windows 跳过） |
| 47 场景迁移 | `reports/t15/oracle-coverage.json`：23 flow + 14 kernel + 10 通道套件 = 47 全覆盖，缺号即失败 | **pass** |
| 11 语义 mutation | `reports/t15/mutations.json`：executed 11 / killed 11 / survived 0 / infra 0 | **pass** |
| 47×2 分辨率 | `tests/integration/test_resolution.py`：1440×2560 下决策与坐标兜底一致 | **pass** |
| 语料健壮性 | 356 真 TSV + 全 XML 不崩、可复现（`tests/integration/test_corpus_robustness.py`） | **pass** |

## 2. 任务完成度（T00–T19）

| 任务 | 状态 | 关键提交 / 证据 |
|---|---|---|
| T00 测试可信 | ✅ 完成 | `5bdecc4`；harness G0 |
| T01 基线与 oracle | ✅ 完成 | `2af8ce5`；`contracts/baseline/behavior-v1.json` 47 例 |
| T02 工程与合同冻结 | ✅ 完成 | `bd16375` `5166554`；`contracts/`、domain 合同 |
| T03 执行器确认 | ◐ 评估完成、ADR 待定 | `maaframework-evaluation.md`；后端裁决随 T18a |
| T04 真图语料 | ✅ 完成（含黑帧负样本） | `2b1ecdf`；544 文件索引 |
| T05 配置与 profile | ✅ 完成 | `2134f17`；TOML 严格装载 + 旧 conf 兼容 |
| T06 设备 worker | ✅ 端口/适配/夹具完成 | `7eb6194`；fake 语义 + adb 适配 + 能力边界 |
| T07 OCR 与预处理 | ✅ 离线完成 | `943ab02` + 预处理 `8f84d87`；挑战者 `657969d` |
| T08 锁与状态 | ✅ 完成 | `b4a1001`；flock/日标记/账本/journal |
| T09 证据与计时 | ✅ 完成 | `97606dd`；内容寻址工件 + JSONL 事件 |
| T10 通知 | ✅ 完成 | `9387390`；五分支正文 + 单次发送 D07 |
| T11 流程状态机 | ✅ 判定核完成 | `ea6236f` `ee928c1`；verify/终态/步骤/收尾 |
| T12 定位与事实 | ✅ 完成 | `c50fe41`；norm/连续段/TSV/XML/region/坐标 |
| T13 回放与报告 | ✅ 完成 | `c958234`；exact/trace/diff + 单文件 HTML |
| T14 接通 CLI | ✅ 编排完成 | `92e4253` `007786b`；退出码全表 + run_once |
| T15 整合门禁 | ✅ 完成 | `9a8cc07` `a5e8ef4`；47 场景 + 11 mutation |
| T16 逐项优化 | ◐ 离线四件完成 | `921a2a3`(基线) `529ddd7`(共享) `8f84d87`(缓存) `83e43c8`(引擎适配)；**晋升需真机实测** |
| T17 打包安装回滚 | ◐ 离线件完成 | `fa4fe6f`；stdlib wheel + 不可变 release + 原子指针；**真实 staging 待授权** |
| T18a 通道资格 | ⏸ 待授权 | 真机只读联调（不签到），需你点头 |
| T18b 自然日验证 | ⏸ 待授权 | 真机自然日，需你点头 |
| T19 发布移交 | ⏸ 未开始 | 依赖 T18 |

## 3. T16 数据结论（真数据，非估计）

- OCR 墙钟（356 次真实调用）：psm11 p50 **1.41s**/p95 2.91s；psm6 p50 **1.06s**/p95 1.97s。
- 纯感知：parse_tsv p50 **0.89ms**、候选生成 p50 **1.27ms** → 相对 OCR 可忽略。
- 调用计数（结构指标）：旧每目标重跑 **69 次/帧** → 同帧共享 **9 次**（**-87%**），
  语义=只减「无目标需要」的调用；已在 `perception/observe.py` 落地并有计数测试。
- RapidOCR 挑战者（同 12 帧）：召回 ≈1.58× Tesseract，CPU 耗时 ≈5.28× → **维持
  Tesseract 默认**，RapidOCR 作为空读回退/GPU 场景备选（`t07-rapidocr-challenger.json`）。

## 4. 已知风险与缺口（照实写）

1. **端到端未接真机**：`run_once` 通过 `ScreenPort` seam 注入事实；真实「设备采集+OCR+
   感知」绑定（device→vision→perception→flow）尚未在真实硬件上跑过。属 T18a 范畴。
2. **B01–B09 兼容差异**：见 `contracts/baseline/discrepancies.md`；B04（文字枪弱证明）、
   B05（rc0&lit0 不可达兼容分支）、B07（rc≠0 只 HOME）、B08（同名 Activity 残留风险）
   已在代码显式标注并有测试/注释，但 B08 无法用坐标消除。
3. **WSL 子进程坑**：Python 子进程调 `wsl.exe` 在本机返回 -1（交互式正常），故 tesseract
   基准复用 T07 原生测量；生产在 Debian 内跑无此层。
4. **systemd/安装未实跑**：候选单元与 release 脚本有离线故障测试，但未装到真实主机；
   Persistent 补跑与跨日期 journal 需 T17 真实 staging 验证。
5. **私有语料不入库**：`pdd-corpus-private/`（含昵称/券面）仅本机；CI 无该目录时健壮性
   测试跳过（不误红）。
6. **10-29 场黑帧**：整场熄屏纯色帧，保留为负样本；标注时单列 class=blank。

## 5. 下一步操作手册（均需授权后再做）

### 5.1 T18a 早期通道资格（只读，不签到）
```bash
# 前置：确认手机在线、与日常签到定时器错峰（每日 10:00 ±3min 触发）
adb devices                                   # 期望 serial 且 state=device
python -m pddcheck.cli.doctor                 # 确认 tesseract/账户/锁
# 只做：连接→一次 screencap+uiautomator dump+焦点→落证据；绝不 tap/领取/兑换
# 产出：G1c 通道资格结论（backend/冷启动/取消/几何/freshness）回填 T03/ADR
```
### 5.2 T17 staging 安装（不动现役 timer）
```bash
python scripts/release.py --root /opt/pddcheck-staging build --version 0.1.0
python scripts/release.py --root /opt/pddcheck-staging expand 0.1.0
PDDCHECK_ROOT=/opt/pddcheck-staging PDDCHECK_PYTHON=python3 packaging/launcher.sh version
# 校验后 switch；pause/resume/rollback 演练；确认不触碰 systemctl 现役单元
```
### 5.3 T16 端到端实测（真机一轮）
```bash
# 用 run_once 接真实适配器跑一轮（拿到真实每帧取数/耗时），对比基线：
# 期望：每帧 OCR 取数由 69 → 9（-87%）；耗时降幅 = 减少通道数 × 单通道耗时
```

## 6. 复跑方式

```bash
# 全部离线测试（Windows smoke）
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests
# 语料基线与挑战者（需私有语料与 .venv-rapid）
python scripts/bench.py --ocr-summary reports/t07/batch-summary.json --tsv-dir <ocr-v1> --out reports/t16/baseline.json
python scripts/callcount.py --frames 178 --out reports/t16/callcount.json
```

> 变更历史见 `contracts/integration-log.md`（共 17 条，含每次踩坑与修正）。
