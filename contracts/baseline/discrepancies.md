# 代码/文档矛盾台账 B01–B08

来源：acceptance.md §3 的结论 + baseline-oracle 的行号取证（pdd.sh = 8bd6e038 快照，2073 行）。
原则：**兼容答案以源码为准，不以简化说明为准**；迁移期不得由模块作者临场「修正」，
每条要么保留（compat），要么挂到显式工程变更（D0x，见 acceptance.md §4）。

| ID | 实际源码行为（证据） | 文档说法 | 迁移决定 |
|---|---|---|---|
| B01 | `load_ocr_conf` L316-318：conf 不在**或读不了**都 `return 0` 回退内建默认；`status` L2036 明说 unreadable→用内建默认 | states-and-exit-codes.md L118-120 说 unreadable 停 78 | compat 保留回退并记 warning；新 TOML 不可读才失败（D06），不悄悄改变旧行为 |
| B02 | 配置 78 出口在派发前 L397-404（notify 走不到 → **0 推送**，用例 44-46）；缺 tesseract 的 78 在 `cmd_run` 内 L1540-1543 → **先推 1 条**「PDD ❌ 缺 tesseract」再 return 78（用例 02）；69 在 L447-450 同为静默 | 部分文档把 78 一概写成「不通知」 | 按失败原因区分通知行为；测试按因断言，不按 rc 一刀切 |
| B03 | `cmd_run` L1533：RUN_DIR mkdir 失败 `return 73`；states 退出码表没有 73 | 文档缺失 | 增补 73 的运维语义与测试；新程序存储错误显式记 operational_status（D04） |
| B04 | `verify_light` L1382-1388：认到字的枪在点前/点后次数都读不到时 WARN「按原样算过」并 return 0 | states 开头说「算成功的口径只有数字变小」 | compat 保留为 `LEGACY_TEXT_WITHOUT_COUNTER` 证据档，报告必须如实标注，不得写成数字已核实（I09）；v2 收紧与否单独立项 |
| B05 | `cmd_run` L1617-1621：rc=0 且 lit∈{0,3} → 最终滑动+写标记+账本清 0 | states 文档 lit=0 写「按失败处理」 | 静态分析：现配置下 rc=0&&lit=0 不可达（lit 必为 1/2/3/4 或 rc=6），lit=3 是正常路。compat 保留；新状态机检出该不可达组合必须报 INTERNAL，不静默换语义 |
| B06 | `cmd_status` L2030-2032 会跑 `device_online`（L643-645 adb devices）与 tesseract --version；bootstrap L291-297 对**所有**子命令（含 status/replay）都读 PUSH_URL_FILE | calibration.md 说 status 无设备操作 | live status 保留；新增 `--offline` 纯本地路径：不构造 live 适配器、不读端点（D05），差异显式登记 |
| B07 | 收尾三分支 L1628-1637：rc0&非NO_CLOSE→force-stop+HOME；rc0&NO_CLOSE(lit2/4)→**零动作**；rc≠0→仅 HOME。而 L1535-1549 的 marker/缺tesseract/掉线/锁屏四条早退**无 HOME** | 「跑完会关 app」的笼统说法 | 按完整 trace 区分路径；绝不统一 finally 无条件 HOME（会破坏 I02：lit2/4 后零动作） |
| B08 | `focused_act` L1443-1446 无斜杠返空；`is_home_page` L1448-1456 子串匹配（同名 Activity≠同页）；`foreground_pkg` L683-690 有标签退回；`require_pdd` L692-703 fail-closed | 入口守卫看起来总在岗 | 无斜杠帧上 focused_act 为空 → `do_step` 的首页守卫（L1092）不触发，只会归因错（README 已知残留 11）。迁移：UNKNOWN 显式阻断（D02），不把「读不到」解释成「已离开首页」 |

## 用例语义补充要点（来自 47 例表精读，供 T15/oracle 使用）

1. 早退用例（1,2,3,4,5,44,45,46）stdout 无 `lit=` 行 → oracle 的 lit 记 absent。
2. no-adb 在 L449 退出 → **0 推送**；no-tesseract 恰推 1 条。
3. locked 留 1 个 `KEYCODE_WAKEUP` key 事件（非 tap/BACK）。
4. wrong-foreground 的 `launch_app` L1438 发 1 次 BACK（backs=1，0 业务 tap）。
5. rc≠0 收尾有孤立 `KEYCODE_HOME`（L1636）→ tail-2 判定 close=0。
6. prize-take-coord：pill-1/2 TSV 空 → 退 `COORD_take(359,752)`「按量好的中心收」；
   prize-take-ocr：P2_TAKE 命中 → method=band@(244,762)。桩 tesseract 的 HDR 使 band TSV
   文件恒非空 → pill 兜底几乎每轮都会跑。
7. entry-swallowed-back：countfile 第 3 行喂 after-back=3，重进分支不触发，taps=4。
8. pend-verify-4 的 sed（8 空格缩进）只关 `cmd_run` L1567 的点前 pend 检查，
   `proof_ok` L1209（2 空格）未动 —— 这正是能走到 `verify_light` return 4 的机制。
9. count-unreadable-coord 计数序列 4,4,'','',5,''：'5' 喂重进后的 bag proof，
   最终 after 仍空 → coord → rc6，taps=4 backs=0。
10. browse 滑动次数是墙钟函数（SBX 里 BROWSE_SECONDS=2 + 桩瞬时返回 → 数百次 swipe）：
    T15 只能断言「≥1 次 browse swipe」，不能钉次数。
11. 720→1440 折算：整 2 倍无舍入歧义；含几何 EXPECT 的 7 条 ——
    下滑 x=1080 2400->1400（happy-ocr）、bag coord 200 1790（bag-not-found /
    entry-swallowed-stuck 的 NOLOG）、bag ocr 870 1048（bag-right-slot）、
    中心收 718 1504（prize-take-coord）、light coord 1196 570（happy-coord /
    count-unreadable-coord）；rc/lit/marker/taps/backs/push/close/title 全部分辨率不变。
12. 环境依赖：browse-band-psm6 / used-band-psm6 / conf-band-psm6 / prize-take-ocr /
    happy-pill-band / already-lit-pill 六例必须 python3+Pillow（或 sandbox/pylib 兼容层）
    才能绿 —— 无 PIL 是环境红，不是判据红。
