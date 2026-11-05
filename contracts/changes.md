# 变更记录（contracts/changes）

公共合同（类型语义、字段、行为口径）的任何改动必须先记在这里再动代码。
编号规则：D = 预先批准的工程变更（acceptance.md §4）；C = 执行期修正（带证据）。

## 预先批准的工程变更

D01–D08 见 [acceptance.md §4](../docs/refactor-v2/acceptance.md)。本文件不重复正文，只记执行状态：

| ID | 状态 |
|---|---|
| D01 presence 显式一次 | 规划冻结，未实现 |
| D02 焦点/新鲜度/未知统一门禁 | 规划冻结，未实现 |
| D03 运行锁 + 日标记后才建设备 | 规划冻结，未实现 |
| D04 不可变工件/原子状态 | 规划冻结，未实现 |
| D05 offline 能力隔离 | 规划冻结，未实现 |
| D06 新 TOML 严格校验 | 规划冻结，未实现 |
| D07 通知严谨成功判定 | 规划冻结，未实现 |
| D08 懒执行/同帧共享/后端切换 | 规划冻结，未实现 |

## 执行期修正（C 系）

### C01 2026-11-06 — T00 桩 curl 接受组合短开关
- 证据：首跑 720 矩阵 42/47 红，`桩严格违规:curl: 未知开关 -sk`；pdd.sh:1478 实际调用
  `curl -sk -m 15 -G …`。
- 修正：sandbox/bin/curl 增补 `-sk` 等组合形式白名单。用例语义零改动。

### C02 2026-11-06 — T00 分类器 shafile 参数误当 JSON 文本
- 证据：`json.loads(a.shafile)` 把路径当 JSON 解析，`Expecting value: line 1 column 1`；
  自检 8 向量覆盖不到真跑的 classify 路径。
- 修正：改为 `json.load(open(a.shafile, encoding="utf-8"))`。

### C03 2026-11-06 — T00 铺装丢 PIL 目录层级
- 证据：staged `pylib/PIL/` 变空命名空间包，`cannot import name 'Image' from 'PIL'
  (unknown location)`；`basename` 把 PIL/*.py 平铺进 pylib/ 根。
- 修正：staging 按 `pylib/PIL/$(basename)` 落位；selftest 单独复制。

### C04 2026-11-06 — domain 类型自洽（ComponentStatus 枚举）
- 证据：test_capture_json_roundtrip 首版用字符串与枚举校验冲突。
- 修正：component_statuses 定死 ComponentStatus 枚举；JSON 序列化转字符串、反序列化转回。
