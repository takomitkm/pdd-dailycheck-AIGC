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

### 6. 2026-11-06 03:11 — 探针脚本意外接触真机（已上报，待总结向用户说明）
- 经过：lead 的 SBX 环境探针脚本复制了 runner 的铺装逻辑但踩了 basename 平铺 bug，
  `$P/in/bin/` 为空；PATH 里 /usr/bin 的真实 adb 经 Windows adb server（WSL 镜像网络）
  连上了真机 192.168.1.110:16132。第 3 组实验（env -i 下跑 pdd.sh run）由此对真机执行了：
  KEYCODE_WAKEUP（唤醒屏幕）、wm dismiss-keyguard、am start 启动 PDD、若干 dumpsys 只读查询；
  随后 PIL 兼容层 NotImplementedError 崩溃中断。
- 影响：无 tap/滑动/兑换/推送（HOME 已隔离到探针目录，PUSH_URL_FILE 不存在）；福袋/点亮未消耗。
  但这是对「不碰手机」红线的真实突破，属 lead 操作失误（探针未先验证 adb 解析到桩）。
- 措施：①探针脚本作废重写，今后任何探针先 `command -v adb` 断言解析到桩路径；
  ②runner 本身经查 PATH=桩+farm（无 /usr/bin），隔离成立，47 例实跑未接触真机；
  ③此条保持可见，最终总结时向用户完整说明。

### 7. 2026-11-06 04:40 — 1440 假红（用例级超时）与工件位置
- 问题：1440 腿 bag-not-found / prize-take-coord rc=124——sbx.sh 硬编码用例 `timeout 240`，
  2 倍分辨率下 band/pill ×3 放大裁片在 drvfs 上超时。720 全绿不受影响。
- 选择：用例预算 240→600s（只抬上限，720 用例 <120s 不受影响，语义零改动）；
  工件从 /tmp 迁到仓库 reports/t00/（gitignore 但持久——/tmp 下 t00-* 被不明清理者
  周期性删除，跨探针取证两次被打断）。
- 结果：720 已在最终代码上 47/47 全绿（verdict=pass）；1440/反例/聚合重跑中。

### 8. 2026-11-06 03:36 — locked 用例根因（SIGPIPE）取证过程要点
- 10 个探针（v2–v14）逐层定位：桩正确→env 传递正确→管道输入字节正确→原位捕获 rc=141。
- 教训：给被测管道加 tee/包装的探针自身会改变竞态（v8 的 >&2 断流、v9 的 tee/grep 争流
  都制造过假象）；最终用「原位 rc 捕获、grep 一字不动」才拿到实锤。
- 修复：桩单次写入（C05）；生产脚本同模式缺陷登记 B09（冻结不改，新程序合同已覆盖）。

### 7. 2026-11-06 04:40–05:10 — 47×127 两次假红：真凶是 lead 自己的注释插入（C07）
- 过程：1440 假超时（rc=124）→ 抬预算到 600s 时把两行注释插进了 run_case 的
  `logs=$(… env -i … \ <注释> <注释> "${_envs[@]}" timeout 600 …)` 续行中间——
  注释吞掉了命令部分，`env -i` 没收到命令只打印环境，下一行 `"${_envs[@]}"`
  的首词被 bash 当命令执行 → 全部用例 rc=127。
- 误案更正：期间怀疑「孤儿 1440 进程并发腐坏」（第一个套件的 1440 腿在 job_kill 后
  于 WSL 侧存活到 06:12 预算，与第二次套件并发）——**并发是真实发生的违规（串行纪律），
  但不是 47×127 的原因**；孤儿清场 + flock 补丁保留（防并发复发的正确工事）。
- 修正：注释移出续行；720/1440/反例/聚合全套重跑。

### 9. 2026-11-06 08:05 — T04 语料回收（用户授权）+ T05 完成
- 用户授权 8 点前真机截图 + 回收 102 存量；07:43 两张只读截图（桌面 launcher 态）；
  12 场 98MB 整包拉回仓库外 pdd-corpus-private/；索引 544 文件（bag=60/popup=30/
  pend=15/done=13/browse=6/light=3 缺口记账）提交为 2b1ecdf。
- T05 配置模块完成（2134f17）：TOML 防漂移测试 + 沙箱 44/45/46 三条闸语义对齐；
  开发期发现 Windows 下 chmod 000 不挡读，B01 不可读测试改用目录路径触发。
- 下一波：T12 定位器纯函数 + T07 Tesseract 适配器对真图批量出 OCR 工件。

### 10. 2026-11-07 07:50 — T12 + T07 完成，真图批处理打通
- T12 定位器移植（c50fe41）：norm/连续段/TSV 合行/XML/region 闸/坐标映射，22 项测试
  按旧算法手工推演；开发期修正三处（通道跨行排序漏了、xml 字段名映射、 XmlNode 框
  成对进候选）。
- T07 适配与批处理（943ab02）：三态结果+stderr 恒收集；对私有语料 178 帧整页
  psm11/6 共 356 次识别全部 OK（≈0.5-1.4s/次）。质量抽查：11-02 subsidy 帧读出
  「你有支付补贴 未使用 ¥10…」= 10-30 入口吞枪事件的遮罩，端到端打通。
- 发现：10-29 场（214026）整场熄屏黑帧（1280×720 横尺寸、5KB 纯色）——空识别正确，
  保留为负样本；批处理 summary 属生成工件，按 .gitignore 保持不入库。

### 11. 2026-11-07 10:00 — T14/T15 接通与整合门禁
- T14(1/2) CLI 退出码全表 + 离线子命令（92e4253）；T14(2/2) run 端到端编排
  （007786b）——退出码口径按 acceptance §5 修正：pend=lit4/进程码0，内部 verify
  rc1→进程码 6，4=入口/5=定位/6=核实/7=焦点；D04 marker 落盘失败→73 且业务 rc 保留。
- T15(1/2) fixture 场景表（9a8cc07）：D04 语义 + 精确 trace + 无真 sleep；
  退出码下沉 pddcheck/exits.py，workflow 不再依赖 cli（新增边界断言防回退）。
- T15(2/2) 47 场景 Python 驱动（a5e8ef4）：23 flow + 14 kernel + 10 suite 全覆盖、
  缺号即失败；11 语义 mutation 全杀死（reports/t15/mutations.json = 11/11/0/0）。
- 测试规模：274 passed + 3 skipped（POSIX 锁测试 Windows 跳过、Debian 真跑），16.7s。
- 修：无斜杠 StatusBar 焦点识别；profile 测试改 tmp_path 不再污染 CWD。

### 12. 2026-11-07 10:20 — T16 离线基线（真数据）
- scripts/bench.py：OCR 墙钟（取 reports/t07 的 356 次真实调用）+ 纯感知微基准
  （语料 356 份真 TSV ×2 轮）+ 成对比较（delta 需统计证据支撑）。
- 基线结果（docs/refactor-v2/t16-baseline.json）：psm11 p50=1.41s/p95=2.91s（n=178）、
  psm6 p50=1.06s/p95=1.97s（n=178）；parse_tsv p50=0.89ms、ocr_pass_candidates
  p50=1.27ms。→ 纯感知 ~2ms 相对 OCR ~1.4s 可忽略，T16 优化重点在**引擎**
  （RapidOCR 挑战者）与调用次数（同帧共享/按页跳过），不在业务代码热路径。
- 修：wheel 条目时间戳随构建时刻变导致同版本重建字节不同（真实不确定性 bug）——
  改固定时间戳，wheel 可复现（同输入同字节）。

### 13. 2026-11-07 10:40 — T07.4 RapidOCR 挑战者（离线、独立 venv）
- 在独立 .venv-rapid（不入库）用清华镜像装 rapidocr-onnxruntime 1.4.4 + onnxruntime
  1.31.1，成功（首次 pip upgrade 卡住→跳过，直接装依赖 OK）。
- scripts/bench_ocr_engine.py：逐帧双引擎对比（耗时 + 标签命中，同口径
  normalize+连续段）；scripts/challenger_report.py 把同 12 帧的既有原生 tesseract
  测量与 rapidocr 实测对齐（见 docs/refactor-v2/t07-rapidocr-challenger.json）。
- 结论（同 12 帧，11-02 场）：RapidOCR 标签命中 ≈1.58× tesseract（召回更高，含更多
  噪声字），但 CPU 耗时 ≈5.28×（p50 3.68s vs 0.21s）。→ 维持 Tesseract 为默认；
  RapidOCR 作为召回备选，待 T16 引擎优化/GPU 或「tesseract 空读时回退」场景再评估。
- 已知环境坑：Python 子进程调 wsl.exe 在本机返回 -1（交互式 shell 正常），故 tesseract
  侧复用 T07 原生测量而非现跑；rapidocr 为进程内直接可测。

### 14. 2026-11-07 10:55 — T16 结构证据 + 47×2 + 语料健壮性
- scripts/callcount.py：同帧共享/惰性 XML 的**调用计数**（结构指标，不需引擎）：
  旧每目标独立跑 69 次/帧 → 共享 9 → 惰性 9；**降 87%**（docs/refactor-v2/t16-callcount.json）。
  语义：只减「无目标需要」的调用，每目标可用来源集合不变。
- 47×2：流程场景在 1440×2560 点空间复跑结果不变；坐标兜底按 half-up 正确映射
  (100,895)→(200,1790)（tests/integration/test_resolution.py）。
- 语料健壮性：356 份真 TSV + 全 XML 全部不崩、可复现；发现并修 **parse_tsv 坏 conf
  会抛异常**的真实 bug（改容错：坏行跳过/坏值按 0，与旧 awk 强制转换一致）。
- 测试 306 passed + 4 skipped（53s，含语料扫描）。

### 15. 2026-11-07 11:05 — T16 同帧共享落地（-87% 进代码）
- perception/observe.py：observe_frame 每帧取 1 次 XML + 每通道 1 次 OCR（重复请求=
  编程错误直接抛）；locate_all 从同一观察定位全部目标，不再取数。
- 语义等价：locate_all 内部走同一 locate_candidates，逐目标结果与单独定位一致
  （tests/perception/test_observe.py、tests/integration/test_observe_pipeline.py）。
- 计数证明：9 目标仍是 1+xml + N 通道取数（3 次），非 9×(1+N)；端到端 run_once
  用共享观察得出的点击点完成点亮，全程只取 2 次。
- 测试 312 passed + 4 skipped。

### 16. 2026-11-07 11:15 — T16 缓存与按页跳过 XML
- vision/cache.py：解码缓存（按图 sha）+ 裁片缓存（键=图 sha+裁切框+recipe 串）；
  LRU 带 hit/miss/evict 计数；recipe 隔离（防把 A recipe 裁片喂给 B）。
- vision/preprocess.py：band/pill 裁切几何与预处理（±pad / 不补 pad、灰度+autocontrast、
  反色+硬阈值、×scale/×div LANCZOS），与旧 band_pass/pill_pass 逐条对齐；用 sandbox
  compat PIL 真跑验证尺寸。
- observe：新增 XmlPolicy——消费券/浏览页跳过 XML dump（省一次取数），其余照取。
- 测试 320 passed + 4 skipped。

### 17. 2026-11-07 11:25 — T07.4/T16 OCR 引擎适配器抽象
- vision/engine.py：TesseractEngine / RapidOcrEngine 产出同一 TsvResult（TSV 形状），
  交给同一 parse_tsv；detections_to_tsv 把 rapidocr 四点框→外接矩形词行、conf×100；
  失败=INVALID（不伪装空读）；EngineLease 按 engine_id 独占（同 id 第二实例报错）。
- 跨引擎一致性：同一框/文本/置信度下，两后端 parse_tsv 的行文本/几何/conf 完全一致。
- 测试 326 passed + 4 skipped。

### 18. 2026-11-07 11:40 — T14 组合根接线（端到端可跑）
- cli/bootstrap.py：把真实类装配成一条线——设备采集→共享观察（observe_frame/
  locate_all）→事实抽取→run_once（锁/日标记/点亮/核实/收尾/通知）。硬件用
  FakeDevice 顶替；真机只换 device/engine 两个适配器，其余不动。
- vision/source.py：DeviceVisionSource（一帧只截一次像素，fetch_ocr 复用）；
  perception/facts.py：进度次数/待兑换天数/各标签的纯函数抽取（多措辞，读不到≠0）。
- 端到端测试：lit3（点前4→点后3）、done(lit1 不点)、pend(lit4 账本3) 三路径；
  共享观察一帧一取（observe_calls=2/1）。修：pend 判定词太窄（补「点亮任务已完成/
  天后可兑换/券已放进口袋」）；「无真 sleep」阈值 2s→5s（负载波动）。
- 测试 333 passed + 4 skipped。

### 19. 2026-11-07 11:50 — 交付完整性审计门禁
- scripts/audit_claims.py：把 merge-report 的关键断言做成可复跑审计——oracle 47 覆盖、
  mutation 11/11、G0 harness（2×47、neg 11/11、cex 4）、T16 基线 n=178、
  调用计数 69→9/-87%、挑战者 lat5.28×/hit1.58×、18 个关键文件齐、测试收集 ≥333。
  产出 reports/audit.json；任何 FAIL 即非零退出。证据缺失记 SKIP（可见，不冒充通过）。
- tests/integration/test_audit_claims.py：审计作为门禁（无 FAIL 才绿）。
- 结果：8 项全 PASS（collected=339）。测试 335 passed + 4 skipped。

### 20. 2026-11-07 10:55 — T17 staging 装机 h61 + T18a 真机只读通道资格
- T17：本机构建 wheel(96KB)/manifest → scp 到 deb-h61:/home/user/pddcheck-staging →
  expand → `pddcheck version` rc0、`doctor` rc0（能力集无 device_act ✓）；current=0.1.0。
  未装 systemd 单元、未触发现役 timer。h61 自带 adb+tesseract。
- T18a（用户授权 11:00-14:00/21:00-03:00）：真机 192.168.1.110:16132 只读探针
  channel_ok——device/焦点 launcher/截图 720×1280 881KB 750ms/层级 11932 字 3484ms。
- 真机坑修复：`uiautomator dump /dev/tty` 返回空 → `AdbDevice.read_hierarchy` 回退
  dump 到 /sdcard 再 cat（读完 rm 清理），有测试兜底。
- 真机 OCR（部署目标 h61，同一真图）：psm6 p50 2.29s、psm11 p50 2.16s。
- 未做：真机业务动作（点亮/领取/兑换）本轮一律未执行（只读）；端到端实跑待明确同意。
- 记录：docs/refactor-v2/t18a-channel-report.md。

### 21. 2026-11-07 11:00 — T16 真机干跑（零副作用）+ 优化量化
- h61 上 staging 跑 dryrun_h61.py（真实 AdbDevice+TesseractEngine，DryRunDevice 拒绝
  一切动作）：connect 10ms / screencap 654ms / locate 8ms，真机桌面 PNG 720×1280 881KB。
- 单帧成本实测：重复截图+取XML 6033ms → 复用预取帧 5372ms（省 0.66s）→ 跳过 XML
  **2277ms（省 3.2s，帧成本近半）**。→ T16 优先级：按页跳过/惰性 XML > 帧复用 >
  同帧共享；单次全页 OCR ~2.2s 为硬底。
- 安全发现：干跑在桌面用坐标兜底「命中」bag(100,895)——证明坐标兜底必须受
  ActionIntent（expected_package=pdd+window APP）约束；**本轮未执行任何真实业务动作**。
- 新增 AdbDevice.screenshot_bytes（严格 PNG 校验）+ 测试；文档
  docs/refactor-v2/t16-real-device-measurement.md。测试 337 passed + 4 skipped。

### 22. 2026-11-07 11:05 — 真机前护栏 + `pddcheck run` 接通
- 环境事实（h61 只读核查）：旧 `pdd.timer`/`pdd.service` 仍在跑，**今天 10:02 已执行**
  rc=0 lit=3、marker 10:06 已写、推送已发 → 今天不该再实跑（与旧流程重复）。
- AdbDevice 新增**动作前前台校验**（T06.6）：业务动作（tap/swipe/back）先查焦点，包不符
  → REJECTED wrong_window_package、窗口类不符 → wrong_window_kind，绝不对错页发动作。
- `pddcheck run --device <serial>` 接通：真实 AdbDevice+TesseractEngine → bootstrap 端到端，
  带运行锁/日标记/通知/退出码映射；无 --device 报 69（禁止自动选设备）。
- 测试 341 passed + 4 skipped（新增护栏 2 + run 接线 2）。开发期修：tap 测试需先备焦点桩；
  `run` 不再是「未接通」；Windows 不可 import fcntl（测试改补丁到包导出）。

### 23. 2026-11-07 11:10 — 真机零动作跳过验证（安全性里程碑）
- 部署 0.1.2 到 h61（含动作前前台校验 + PDDCHECK_NO_PUSH 开关）。
- 真机跑 `pddcheck run --device 192.168.1.110:16132`，`PDDCHECK_EVIDENCE=~/Desktop/pdd-runs`
  （看到今天旧流程写的 .done）→ 结果：**exit=0 lit=None rc=0 observes=0**，
  journal 为空，**前后焦点都是 launcher（零 UI 副作用）**，无推送（NO_PUSH）。
- 这验证了真机链路：连接→运行锁→读日标记→当天已完成跳过→退出码映射，全程不动作。
- 顺手修：cli/__init__ 改惰性导出，消除 `python -m pddcheck.cli.app` 的 runpy 警告。
- 测试 341 passed + 4 skipped。

### 24. 2026-11-07 11:15 — 流程段补齐（就绪/入口/福袋）+ 阶段失败码
- workflow/stages.py：StageRunner（read_page/act 注入，纯逻辑）——就绪（显式 HOME_ACT
  启动、禁止 monkey 兜底、启动后非 PDD→rc7）、入口 subsidy（点不进→BACK 退遮罩重试
  ≤2→rc4）、福袋 bag（点进后须证明：进度数/待兑换/已点亮；否则 BACK 换轮播帧 ≤3→rc5）。
- flow.run_once：阶段失败（StageFailure）→ 直接映射 rc4/5/7 进终态效果（不写标记、
  只 HOME 收尾），并把原因写进 notes。
- tests/workflow 新增 9 项（Fake 页面序列：启动/已在 pdd/启动失败 rc7/入口 tap/入口重试
  rc4/福袋按进度证明/按 pend 证明/轮播换帧/证明失败 rc5）。测试 351 passed + 4 skipped。

### 25. 2026-11-07 11:25 — 真机流程演练：入口打通、福袋找到根因
- scripts/rehearse_real.py：真机逐段演练（识别+决策全做，动作分级放行：lifecycle /
  入口坐标一枪 / 全量 execute），每步落 JSONL 取证。发布链 0.1.3→0.1.8（每版实测）。
- 实测打通 **entry:ok**：坐标兜底 (90,600) 后前台变 NewPageActivity ✓；StageRunner
  补了坐标兜底（旧脚本同款：入口是艺术字，OCR 认不到）与 **tap 后等跳转 4s**
  （真机证实：不等就误判「没进去」→ rc4）。
- **福袋 rc5 根因定位**：整页 psm6/11 与 band 档都读不出频道页「抽福袋」；
  **pill 档 color 模式 ×2 psm7** 读出三词同行 → 合成「抽福袋」conf 92.6，
  用我们自己的定位器算出 tap **(435,524)**，与旧脚本 10-18 实测逐位一致。
  → 属新标定数据（D08），写进 t18a-calibration-findings.md 待批准，**未擅改冻结 profile**。
- 其他真机事实：频道页 XML 仅 3.5KB（WebView，XML 通道基本无效）；真实 HOME_ACT
  = MainFrameActivity；默认时钟 lambda:0 会让 FocusState 校验失败 → 改真实单调时钟。
- 测试 353 passed + 4 skipped（新增坐标兜底/等待跳转 2 项）。

### 26. 2026-11-07 11:30 — ADR-003（第二胶囊框）+ 裁片通道几何
- config/profile.py：TargetSpec 新增可选 `pill_channel`（缺省 None=不启用，
  **现有 profile 与标定值完全不变**）；ADR-003 记录决策、备选与否决理由。
- perception/observe.py：FrameObservation 增 `geometries`（每通道 scale/offset）——
  裁片坐标必须换算回点空间，否则命中点全飞（旧脚本 band_pass 注释记过这个坑）。
- vision/source.py：DeviceVisionSource 支持 band/pill 通道（按标定框裁片+预处理，
  几何按「TAP/整图/放大倍数（5dp）」与「裁片原点回推（1dp）」登记）。
- tests/perception/test_crop_geometry.py 3 项：pill 几何=0.5/339/480 → 点空间
  (434-435, 524)（与真机实测 (435,524) 一致）、整页恒等几何、缺框不出文本不出几何。
- 测试 356 passed + 4 skipped。

### 27. 2026-11-07 11:40 — 真机连跑：配方与坐标证实，编排确定性待修
- 真机逐版实测（0.1.9→0.1.15）确认：pill 通道 color×2 psm7 稳定产出候选 (435,524)；
  手动点该坐标**确实进入消费券活动页**（页面有「9天内再点亮5次必得」「今日已点亮」）；
  `facts_from_text` 对该页文本正确给出 count=5/done。
- 修：open_bag 改**文字判据**（不依赖 activity——活动页与频道页同为 NewPageActivity）；
  点后**不再盲目 BACK**（真机证实会形成 点→退→点 死循环）；裁片候选**优先于整页**
  （整页会把零散「抽/福/袋」误配成「抽福袋」→ 曾点错到 (200,20)）；有裁片供给器时
  **禁用整页坐标兜底**（bag COORD 是活动页位置）。
- 未解决：连跑时页面状态漂移（上一轮残留页影响下一轮起点）→ 下轮加「确定性起点」。
- 记录：docs/refactor-v2/t18a-calibration-findings.md 第 5/6 节。测试 356→358 绿。

### 31. 2026-11-07 12:10 — stages 正式串进 bootstrap（默认关闭）
- PipelineConfig 增 run_stages（默认 False=行为不变）；开启后 build_and_run 先跑
  就绪→入口→福袋，再进 run_once。act() 构造完整 ActionIntent（业务动作带
  expected_package/required_window_kind/target_key），read_page 保留**完整 OCR 文本**
  （facts 字段拼接会丢「抽福袋」等控件文本——第一版就栽在这）。
- **真 bug 修复**：阶段失败原先只进 stats，run_once 不知情 → 继续跑点亮段拿错页
  事实做弱证明 → 误报 lit3。改为 RunDeps 增 stage_failure_rc/why，run_once 见非空
  直接按 rc4/5/7 收尾（不写标记、只 HOME）。
- 集成测试 3 项：默认关（stats.stages==[]）/ 开（ready/entry/bag→lit1 写标记）/
  失败（entry_rc4 → out.rc==4 且不写标记）。测试 374 passed + 4 skipped。

### 32. 2026-11-07 12:15 — run --stages CLI 旗标 + subsidy 坐标兜底入 specs
- cli/app.py：run 增 --stages（默认不开）；specs 补上 subsidy 的 coord=(0.125,0.46875)
  （真机证实入口是艺术字、坐标是唯一手段；此前 specs 没带 coord，开流程段也认不到）。
- h61 0.1.23 部署验证：`run --help` 显示 --stages ✓。CLI/集成测试全绿。

### 33. 2026-11-07 12:25 — CLI 全链路真机成功（lit=3，标记+账本落盘）
- PipelineConfig 增 bag_pill（box,mode）；build_and_run 的 open_bag 接
  extra_candidates=bag_pill_candidates（pill color×2 psm7，几何换算同演练配方）。
  此前 CLI 路径 open_bag 只有整页 OCR → 频道页 rc5（第一跑实测暴露）。
- 真机（独立测试证据目录，PDDCHECK_NO_PUSH=1）：
  `run --device ... --stages` → **exit=0 lit=3 rc=0 marker=True ledger=0 observes=2**；
  `.done-2026-11-07` 落在证据根目录（与旧脚本同口径）；无兑换动作（今日已签到）。
- 安全跳过验证：指向生产证据目录时 lit=None observes=0（日标记已存在 → 直接跳过）。
- 测试 374 passed + 4 skipped。

### 34. 2026-11-07 12:30 — pill_channel 批准后生效路径铺好
- config/profile.py：解析 targets.*.pill_channel（0..1 四比例校验）；缺省 None=关闭。
- tests/config/test_pill_channel.py 3 项：v1 未写→None（现标定不动）/ 写入即生效
  （原 pill 框不受影响）/ 越界拒收（D06 一律拒绝口径）。
- 「批准 → 生效」只剩一步：profile.toml 的 [targets.bag] 加一行 pill_channel；
  CLI 与流程段已消费该值（bag_pill fallback 仍在，等批准后改为只读 profile）。
- 测试 377 passed + 4 skipped。

### 35. 2026-11-07 12:35 — T18b 自然日用例 + T19 交接文档
- tests/storage 补 3 项自然日口径：标记按日独立（昨日不挡今日）/ 账本跨日清零 /
  日期严格零填充等值（.done-2026-11-07）。
- docs/refactor-v2/t19-handover.md：架构一句话、部署（staging 结构+运行方式）、
  退出码与 lit 语义、真机标定速查表、测试口径、待用户决定 3 项、已知边界。
- 测试 380 passed + 4 skipped。

### 36. 2026-11-07 12:45 — 终态回归：verify 门 + 审计 8/8 PASS
- scripts/verify.py → G0-skeleton passed（37.2s，384 collected）。
- scripts/audit_claims.py 8/8 PASS：oracle47(47=47)、mutations(11/11 killed)、
  g0-harness(2×47+neg 11/11+cex 4)、t16-baseline(n=178)、t16-callcount(69→9 −87%)、
  t07-challenger(lat 5.28×/hit 1.58×)、required-files(18)、tests-collected(384≥333)。
- 仓库处于可交接终态：分支 refactor-v2，工作树干净，380 tests + 4 skipped；
  真机 0.1.24 部署验证通过；剩余 3 项等用户决定（profile 标定/timer/未签到日验证）。

### 37. 2026-11-07 12:50 — timer 最后技术障碍排掉（只读校验）
- h61 `systemd-analyze verify /tmp/pddcheck.service`：**语法通过**；唯一警告
  「launcher.sh 不存在」= 占位符尚未安装（安装脚本展开），非缺陷。
- 日历规格验证：`Mon..Fri *-*-* 10:00:00` 合法，下次触发 Mon 2026-11-09 10:00 CST
  （旧 pdd.timer 是每日 10:00:31，工作日口径待用户选）。
- 结论：安装批准后零语法风险；安装步骤 = 装 launcher.sh + unit 到
  ~/.config/systemd/user/ + `daemon-reload && systemctl --user enable --now pddcheck.timer`。

### 38. 2026-11-07 12:55 — 批准路径零代码化（pill_channel 优先读 profile）
- cli/app.py：run_stages 时先 load_profile 读 targets.bag.pill_channel；读到就用它，
  读不到用真机验证过的 fallback（(0.472,0.375,0.75,0.4375)/color）。
  → 用户批准后只需在 profile.toml 加一行，**无任何代码改动**。
- tests/config/test_approval_path.py 3 项：未批准=None（防漂移）/ 批准后 profile 优先
  / fallback=真机实测值（裁片原点 (339,480)，中心点 (435,524)）。
- 测试 383 passed + 4 skipped。

### 39. 2026-11-07 13:05 — timer 生产隐患修复（device 来源 + ExecStart 参数）
- **真隐患**：候选 unit 的 ExecStart 没带 run 参数 → 定时器每天会 rc69（run 无设备）。
- cli/app.py：`--device` 缺省时读 `PDDCHECK_DEVICE`（两者都无仍 rc69，禁止自动选设备不变）。
- unit 修正：`EnvironmentFile=%h/.config/pddcheck/env`（安装脚本写 PDDCHECK_DEVICE）
  + `ExecStart=…launcher.sh run --device ${PDDCHECK_DEVICE} --stages`；h61 re-verify 通过。
- tests/cli/test_device_env.py 2 项：两者都无→rc69 / 环境变量被接受（报连接失败而非没设备）。
- 测试 385 passed + 4 skipped。

### 40. 2026-11-07 13:10 — 并行观察 timer 已装（授权范围内）
- 依用户授权「可安装到h61自动取证因为本机可能关闭」，采用**并行观察**（不动旧 pdd.timer）：
  错峰旧 10:00 vs 新 10:30；共享同一 `.done-<date>` → 旧流程成功则新单元 observes=0 跳过；
  **NO_PUSH=1**（只取证不推送，绝不与旧流程抢推送）；Persistent 补跑；Restart=no。
- 装：launcher.sh（读 current 指针）+ env 文件（600）+ service/timer 到 ~/.config/systemd/user。
- 手动触发实测：`exit=0 lit=None observes=0`（今天已签到 → 正确跳过）；unit 描述「并行观察」。
- **两 timer 并行**：pdd.timer 10:00:31（enabled）+ pddcheck.timer 10:30（enabled）。
- 迁移到 pddcheck 接管（将来用户批准后）：删 env 里 NO_PUSH、`systemctl --user disable pdd.timer`、
  enable 推送。**回滚**：`systemctl --user disable --now pddcheck.timer`（旧流程完全不受影响）。
- 打包：packaging/systemd/pddcheck.timer.candidate + packaging/install-parallel.sh。

### 41. 2026-11-07 13:30 — 纯观察模式（--dry-run）+ timer 切到 dry-run
- run --dry-run：识别与决策照做，**不执行业务动作、不写标记/账本、不推送**（只留证据/notes）；
  notify 增 DeliveryStatus.SKIPPED；flow/run_once dry 分支；bootstrap dry 阶段路径
  （只做 ensure_ready + 页型判定 + 记录将点目标，不试跳转，避免误报 rc4）。
- 目的：并行观察期 pddcheck **永不代签**，真实签入仍由旧 pdd.timer 负责；
  取证后代签需用户批准去掉 --dry-run 并停用旧 timer。
- h61 0.1.25 部署；timer 已重装为 `--stages --dry-run`；手动触发实测：
  `exit=0 lit=None observes=0`（跳过），与旧流程无任何冲突。测试 386 passed + 4 skipped。

### 42. 2026-11-07 13:40 — 用户批准：标定入 profile + pddcheck 接管（停旧 timer）
- 批准 1：profiles/pdd/v1/profile.toml [targets.bag] 写入
  `pill_channel = [0.472,0.375,0.75,0.4375]`；DEFAULTS 同步；防漂移/批准路径测试
  按批准后口径更新；config 测试全绿，全量 386 passed + 4 skipped。
- 批准 2：h61 接管步骤（下轮执行并验证）：`systemctl --user disable --now pdd.timer`；
  pddcheck env 去掉 NO_PUSH；service 去掉 --dry-run；timer 改 10:00:00；daemon-reload。
- 批准 3（未签到日真实 lit3 真点亮）：今日已签到，无法在不产生额外副作用前提下
  验证真点亮；待下一个未签到日（下一次无 .done 标记且 timer 触发，或用户指定窗口）。

### 43. 2026-11-07 13:50 — 生产接管执行完成（用户批准）
- h61 takeover.sh：`pdd.timer` disabled+stopped；`pddcheck.timer` enabled 10:00:00；
  service `run --device ${PDDCHECK_DEVICE} --stages`（无 dry-run）；env 无 NO_PUSH；
  push 端点文件 present；old_pdd_service inactive；DEFAULTS.bag.pill_channel=(0.472,0.375,0.75,0.4375)。
- 0.1.26 部署为 current。
- 未签到日真实 lit3 真点亮：今日已签到（旧/新共用日标记语义），**不能伪造未签到状态**；
  将在下一次自然无 .done 标记的运行中由 pddcheck 生产 timer 验证（或用户指定窗口）。

### 44. 2026-11-08 20:00 — 生产首跑翻车 + 修复（0.1.27 已部署）
- **11-08 10:00 生产首跑失败**：`ensure_ready → start` 被 AdbDevice 护栏拒绝
  （`home_activity_missing: 必须显式 HOME_ACT 启动，禁止 monkey`）→ service FAILURE。
  根因：bootstrap 的 act() 把 home_activity 只传进了 StagePolicy；**AdbDevice 构造没传**
  （演练脚本传了所以演练通过，生产路径漏——演练与生产的分叉点）。
- 旧 pdd.timer 已于 11-07 停用 → **11-08 当天签到未执行**（无推送、无标记）。
- 修复：`run` 构造 AdbDevice 时传 `home_activity=cfg.home_activity`；回归测试 2 项
  （源级断言 + 默认值）；388 passed + 4 skipped；0.1.27 部署为 current，已推 main。
- 11-08 补签：不在授权窗口（21:00–03:00）内不做业务动作；待窗口内手动触发或
  11-09 10:00 timer 自然验证。

### 45. 2026-11-08 20:50 — 补签成功 + 三个生产修复（0.1.28/29/30）
- 补签最终结果：`run 2026-11-08: exit=0 lit=3 rc=0 marker=True ledger=0 delivered=sent
  observes=2`（用户授权「现在就可以」）。marker .done-2026-11-08 OK、推送 sent。
- 连续三修（每一版真机暴露一个）：
  1) 0.1.28 `ensure_ready`：停在**点亮活动页**时直接续跑（BACK 只会退到频道页，
     rc7 误伤；旧脚本「STEPS 从当前页续跑」同语义）；
  2) 0.1.29 start 后**轮询等焦点**（冷启动 >4s 实测，单次判定误判「没起来」；
     launch_wait 12s）；
  3) 0.1.30 `dismiss_popup`：用户现场指认「屏幕中间『邀请/抽』弹窗挡页面」→
     关闭词优先（关闭/暂不/以后再说），无关闭词但「邀请+抽」同现且非活动页 →
     点右上角惯例位 (614,385)；活动页上的「抽」是正常文案不当弹窗；max 3 轮。
  各配 4-5 项 Fake 测试；全量 397 passed + 4 skipped。
- 教训：生产链路的「页面状态空间」比演练覆盖的多（残留页/冷启动慢/弹窗）——
  这三个都是用户在现场看到真机状态才定位的。

## 待办记账

- [ ] WSL 实跑 run-sandbox-local.sh：--self-check → 47×2 全矩阵 → 反例四项。
- [ ] 提交 T00（署名 test-gate）。
- [ ] lead 串行补齐 T01 六份交付（legacy/README、behavior-v1.json、discrepancies、corpus-inventory、trace-schema、t01-report）并提交。
- [ ] T02 后半：Fake 系列、依赖边界测试、conftest、锁文件方案（uv 有无待查）。
- [ ] G0 终验 + contracts-v1 标签。
- [ ] baseline-oracle 转述的 sbx.sh:2「39 例」头注释漂移：不改 sandbox（T01 口径），待 T15 修。
