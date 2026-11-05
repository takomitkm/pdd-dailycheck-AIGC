# T01 执行报告（基线与 oracle）

日期：2026-11-06（Asia/Taipei）。执行：baseline-oracle（取证）→ lead（接管落盘，用户指示串行）。
基线 commit：`a7d4e95908d9cc4b621df7bea1bb2f68f3842b5d`；pdd.sh SHA256
`8bd6e038…e90`，2073 行（byte 级快照已存 `legacy/pdd.sh`）。

## 方法

1. 全量静态分析：sbx.sh 47 例用例表（a7d4e95 版 486 行）、三个桩、pdd.sh 相关函数、
   docs/（states-and-exit-codes / forensics / calibration / sandbox-testing）。
2. 所有行号证据锚定 `a7d4e95`；T00 对工作区 sbx.sh 的改动经 diff 核实**不改用例语义**
   （只加门禁 plumbing），oracle 不受影响。
3. 全程未运行 pdd.sh、未 SSH、未联网、未读端点/凭据文件。

## 交付清单

| 文件 | 状态 |
|---|---|
| legacy/pdd.sh + legacy/README.md | 完成 |
| contracts/baseline/behavior-v1.json | 完成（47 例逐条：输入/断言/证据行号；720 主口径 + 1440 折算表） |
| contracts/baseline/discrepancies.md | 完成（B01–B08 行号证据 + 迁移决定 + 12 条用例语义要点） |
| contracts/baseline/corpus-inventory.md | 完成（仓库 0 张真图；主机 7 天窗未采集；T04 只能先立 schema） |
| contracts/baseline/trace-schema.md | 完成（有序事件/focus 前置/通知字节/文件写入；2 示例） |

## 未决与移交

- **oracle 的 observed 值未回填**：47 例的 observed 计数（taps/backs/pushes 的实跑值）以
  T00 首跑的 `CASE name=...` 机读行为准，验证一致后由集成人合并——本文件立的是
  asserted 契约，不是实跑结果。
- sbx.sh:2 头注释「39 例」与实际 47 例的漂移：属元数据漂移，不改 sandbox（T00 正在改的
  文件），留给 T15 顺手修。
- corpus：全部真图类缺失，G1b 只能出 schema + 采集规程；采集须等自然机会 + 用户授权。
- trace-schema 的 focus_precondition 与 notify 字节断言是**新增能力**（现役 harness 没有），
  T15 实现时要先在旧脚本上「记录」再「断言」，避免一次性引入大量假红。
