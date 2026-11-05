# legacy/ — 现役基线快照（只读）

本目录保存重构起点的**字节级快照**，供模块迁移与差分验收对照。这里的文件是证据，不是活代码：
**任何修改、运行、部署都禁止**；分析请引用，不要 import。

## 快照内容

| 文件 | 是什么 | 校验 |
|---|---|---|
| `pdd.sh` | 现役主程序快照，2073 行 | SHA256 `8bd6e038fe28c46acfe82f09ce4ae9b25e8e979f559a41843e64bb944c760e90` |

基线锚点：仓库提交 `a7d4e95908d9cc4b621df7bea1bb2f68f3842b5d`（refactor-v2 分支上规划包落库后的树，
pdd.sh 与其上游 `b59d150` 完全一致）。`a7d4e95` 的 pdd.sh blob = `7930b062…`，
sbx.sh blob = `7ea84c25…`；复现命令：

```sh
git show a7d4e95:pdd.sh | sha256sum
git show a7d4e95:sandbox/sbx.sh | wc -l   # 486
```

## 依赖清单（线索只取自仓库文档，未探测任何主机）

| 依赖 | 用途 | 来源 |
|---|---|---|
| bash | 运行时 | pdd.sh shebang；`set -uo pipefail` |
| adb | 无线 adb 设备控制（192.168.1.110:16132，720x1280 点空间） | README / systemd unit ExecStartPre |
| tesseract 5.x + chi_sim | 六档识别（整页 psm11/6、band 7/11/6、pend 6/11/12） | docs/api-attribution.md（5.5.0 实测）、Qoder 历史记录 |
| python3 + Pillow | finder() 匹配器 heredoc、band/pill 裁片（BAND_SCALE=3、autocontrast） | pdd.sh:453 起、:877/:967 的 `import PIL` 闸门 |
| curl | ServerChan 推送（端点在主机 ~/Desktop/pdd-push.url，不入库） | pdd.sh notify() |
| systemd user units | pdd.timer（10:00 + 0-180s 抖动、Persistent）+ pdd.service（oneshot、25min、Nice=10） | systemd/ |

注意：pdd.sh 在本机（Windows）不可运行——`python3` 是商店占位符、无 tesseract、无 PIL；
历史教训见 Qoder 会话 2026-10-09（rc78「缺 tesseract」）。分析本文件不需要运行它。

## 相关产物

- 行为 oracle：`contracts/baseline/behavior-v1.json`（47 例桩沙箱口径）
- 代码/文档矛盾台账：`contracts/baseline/discrepancies.md`
- 真图语料清单：`contracts/baseline/corpus-inventory.md`
- trace 字段规格：`contracts/baseline/trace-schema.md`
- 方法与未决问题：`docs/refactor-v2/notes/t01-report.md`
