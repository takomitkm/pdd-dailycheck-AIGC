# 集成日志（用户指示：串行推进 / 自主测试 / 记录所有问题·试验·选择）

本文件按时间记录重构执行中的问题、试验与选择，最终随总结向用户汇报。约定：每条带日期时间（Asia/Taipei）与「问题/试验/选择/结果」。

## 2026-11-05

### 1. 团队并行模式 → 串行接管
- 问题：两个 durable teammate（test-gate/baseline-oracle）的会话反复崩溃（后台子代理多次 failed no closing message），夜间双双停在 inactive，工作落盘未提交；baseline-oracle 六份交付只完成 legacy/pdd.sh 快照。
- 选择（用户指示）：子 agent 一律串行不并发；lead 直接接管收尾与验证；有问题的解法先自己试（无持久性负面影响的前提下），选择分叉都试、记录、最后汇报。
- 结果：向两位 teammate 发 stand-down，避免双写；后续集成/补写由 lead 串行执行。

### 2. pip 网络路线（T02 测试环境）
- 问题：pip 经本机 mihomo 代理 127.0.0.1:7897 装 pytest 卡死 >7 分钟（两次试验：直连卡死、走代理也卡死）。
- 试验：①默认源直连（卡死）→②代理 7897（仍卡死）→③清华镜像直连（4.5 MB/s，数秒装完 pytest 9.2.0）。
- 选择：repo .venv + 清华镜像装 dev 依赖；代理端口本身在监听（TcpTestSucceeded=True），疑似对 PyPI 大文件中转有问题，未深究。
- 结果：G0-skeleton 门禁 19/19 绿。

### 3. .gitignore 的 bench*/ 误伤
- 问题：旧规则 `bench*/`（标定大图目录）会忽略规划中的 bench/ 测量代码目录。
- 选择：显式豁免 `!bench/`、`!benchmarks/`，另加 `reports/`、`.venv/` 忽略。
- 结果：bd16375 已提交。

### 4. 域模型自洽修正
- 问题：Capture.component_statuses 初版测试存原始字符串与「必须 ComponentStatus 枚举」校验冲突。
- 选择：类型定死为枚举，JSON 序列化转字符串、反序列化转回枚举。
- 结果：test_capture_json_roundtrip 等全绿。

### 5. WSL 环境（T00/T02 本地运行底座）
- 实测：WSL Ubuntu python 3.14.4，无 pytest、无 PIL；Windows 打包运行时 3.12.14 有 python 无 pytest。
- 选择：沙箱（bash 脚本族）走 WSL；pddcheck Python 测试走 repo .venv。test-gate 已自带 sandbox/pylib 纯标准库 PIL 替身（含 3.14 的 pyc，说明它在 WSL 里试跑过）。
- 结果：待本轮 WSL 实跑验证 T00 后记录。

## 待办记账

- [ ] WSL 实跑 run-sandbox-local.sh：--self-check → 47×2 全矩阵 → 反例四项。
- [ ] 提交 T00（署名 test-gate）。
- [ ] lead 串行补齐 T01 六份交付（legacy/README、behavior-v1.json、discrepancies、corpus-inventory、trace-schema、t01-report）并提交。
- [ ] T02 后半：Fake 系列、依赖边界测试、conftest、锁文件方案（uv 有无待查）。
- [ ] G0 终验 + contracts-v1 标签。
- [ ] baseline-oracle 转述的 sbx.sh:2「39 例」头注释漂移：不改 sandbox（T01 口径），待 T15 修。
