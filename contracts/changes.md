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

### C05 2026-11-06 — 桩 adb/window·devices 分支改单次写入（SIGPIPE 竞态）
- 证据：locked 用例稳定 rc=5（应 3）。探针 v14 在 keyguard_up 原位捕获到管道 rc=**141**
  （SIGPIPE）：pdd.sh `set -o pipefail` + `grep -q` 第一行命中即退，桩 window 分支两次
  printf 之间夹着内部 grep，时序变化时 tr/桩被 SIGPIPE 打死 → 「已匹配」被判「未匹配」。
  独立复测同管道 270/270 rc=0——纯竞态，负载相关。
- 修正：桩 devices/window 分支改为变量累积 + 单次 `printf '%b'`。输出内容逐字节不变，
  用例语义零改动。首次跑出的 42 红另含 C01（-sk）叠加。
- 残留：**pdd.sh 生产脚本里 `keyguard_up`（真机 dumpsys 输出巨大，几乎必然 SIGPIPE）与
  `device_online` 同模式**——锁屏检测在真机上本就不可靠，属真实潜伏缺陷，登记为 B09；
  新程序按合同用 Reading 状态机替代管道布尔，legacy 冻结不改。

### C07 2026-11-06 — sbx.sh 注入注释吞掉 case 命令（47×127 假红，lead 自己引入）
- 证据：抬用例预算时把注释插进 `logs=$(… env -i … \ <注释> …)` 续行中间；bash 里注释
  吞掉续行余下部分，`env -i` 没收到命令只打印环境，下一行 `"${_envs[@]}"` 首词被当
  命令执行 → 全部用例 rc=127（out.log 开头是环境列表 + `SBX_COUNT_FILE=…: No such
  file or directory`）。两次全套 47×47 假红同因。
- 修正：注释移出续行；原有「孤儿进程并发」假设更正为误案（见 integration-log §7）。
- 教训：`$()` 续行中间严禁插注释；runner 的 `bash -n` 查不出这种语义错误，
  门禁的 infra 自检要加「out.log 不应以环境列表开头」这类形状检查（T15）。

### C06 2026-11-06 — runner 的 ONLY 传参方式修正
- 证据：`--only locked` 报 127 `ONLY=locked: command not found`；`${ONLY:+ONLY=$ONLY}`
  的展开结果不会被 bash 重新识别为赋值前缀，ONLY 非空时成为命令名。全量跑（ONLY 空）
  不触发，故此前未暴露。
- 修正：改为显式 `export SBX_IN/SBX_ROOT/SBX_SIZE` + `[ -n "$ONLY" ] && export ONLY`。
