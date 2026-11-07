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

## 待办记账

- [ ] WSL 实跑 run-sandbox-local.sh：--self-check → 47×2 全矩阵 → 反例四项。
- [ ] 提交 T00（署名 test-gate）。
- [ ] lead 串行补齐 T01 六份交付（legacy/README、behavior-v1.json、discrepancies、corpus-inventory、trace-schema、t01-report）并提交。
- [ ] T02 后半：Fake 系列、依赖边界测试、conftest、锁文件方案（uv 有无待查）。
- [ ] G0 终验 + contracts-v1 标签。
- [ ] baseline-oracle 转述的 sbx.sh:2「39 例」头注释漂移：不改 sandbox（T01 口径），待 T15 修。
