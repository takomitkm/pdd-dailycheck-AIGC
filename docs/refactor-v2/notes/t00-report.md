# T00 执行报告（测试门禁修复）

完成日期：2026-11-06（Asia/Taipei）。执行：test-gate（主体）→ lead（收尾修复与验证，串行指示）。
基线：a7d4e95 → 交付于 5bdecc4。全程 WSL 本地，无 SSH / 无真机 / 无网络 / 无凭据。

## 交付（详见提交 5bdecc4 与 contracts/changes.md C01–C07）

| 门禁要求（G0a） | 结果 |
|---|---|
| 47×2 全矩阵、机器可判定 | ✅ 720/1440 各 47/47 pass（reports/t00/*/result.json + harness-result.json） |
| 失败/缺用例/执行数不符/基础设施错 → 非零退出 | ✅ sbx.sh 退出码契约 0/1/2/3/4；runner 状态传播 |
| 唯一运行根 + 环境隔离 | ✅ mktemp 根 + env -i 白名单（HOME/TMPDIR 指向用例目录） |
| 桩严格模式 | ✅ 未知 adb/tesseract/curl → 64/65/66 + 留痕；47 例无一依赖宽松回退 |
| 负对照 11 条本地化并聚合 | ✅ executed=11 killed=11 survived=0 infra=0，NEG-GATE pass |
| 反例能让门禁失败 | ✅ 坏 ONLY / 强制超时 / 删桩 / 未知桩命令 四连全部按预期变红 |
| 机器可读结果 | ✅ reports/harness-result.json（GATE_SUMMARY pass=True runs=2 neg=1 cex=4） |
| 无 PIL 环境可跑 | ✅ sandbox/pylib 纯标准库 PIL 兼容层（自检 17/17） |

## 过程中的坑（全部记录于 contracts/changes.md C01–C07 与 integration-log）

1. C01 桩 curl 白名单漏了组合短开关 `-sk`（pdd.sh 实际调用形状）→ 首跑 42/47 假红。
2. C02 分类器把 shafile 路径当 JSON 文本（自检覆盖不到真跑路径）。
3. C03 铺装 basename 平铺丢 PIL 目录层级（空命名空间包）。
4. C05 桩 window/devices 两次 printf + 被测脚本 `pipefail|grep -q` = SIGPIPE 竞态，
   「已匹配」判「未匹配」→ locked 假红；顺带实锤生产脚本同模式潜伏缺陷（B09，冻结不改）。
5. C07 **lead 自己**把注释插进 `$()` 续行中间，吞掉 case 命令 → 两次 47×47 假红；
   期间「孤儿进程并发腐坏」假设为误案（并发确实发生且违反串行纪律，已清场并加 flock）。

## 移交 T15 的已知缺口

- 推送次数（pushes）大多未断言；完整有序动作序列未断言；标题断言是子串非字节级。
- 真图质量与性能不在此门禁范围（见 corpus-inventory 的缺口与 acceptance §8/§9）。
