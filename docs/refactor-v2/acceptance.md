# 行为、质量、性能与发布验收

关联：[总规划](README.md) · [契约](architecture-contracts.md) · [任务](tasks.md) · [Maa后端评估](maaframework-evaluation.md)。所有门禁由数据和退出码判定，不靠日志末尾的 OK 字样。本文件是未来测试规格，本次规划期间没有执行这里的测试。

## 1. 三条验收轨道

| 轨道 | 证明什么 | 不证明什么 |
|---|---|---|
| 行为兼容 | 给定相同有序观察/返回，动作和终态符合既定规则 | OCR真的认得真机、设备当前可用 |
| 图像质量 | 固定真实帧上，完整生产识别链的定位/进度/终态正确 | 所有未来页面改版都正确、真实输入已执行 |
| 性能与真机 | 指定主机、模型、设备、网络和样本下的墙钟时间及实际行为 | 小样本99.9%可靠性、未出现的终态覆盖 |

legacy-parity 先通过兼容轨道，single-device-v2 再通过完整质量与性能门禁。工具后端可以替换，业务与动作合同不替换。

## 2. 冻结业务不变量 I01～I15

| ID | 不变量 | 必须断言 |
|---|---|---|
| I01 | 兑换由人工处理 | exchange永不进入可执行TAP；无COORD_exchange；lit2后无任何设备动作 |
| I02 | 等待兑换保留屏幕 | lit4后无BACK/HOME/STOP/最终滑动；marker写入；通知一次 |
| I03 | done包含已使用 | 沿用当前词表/ROI/已定案语义，不偷偷加第二约束；已使用标题单独分支 |
| I04 | 首轮坐标兜底仍存在 | subsidy/bag/light/take按当前上下文允许；take仅奖励浮层上下文；dialog空别名不自动触发 |
| I05 | 恢复路径禁坐标 | 恢复模式中CONFIG_COORD不能产生动作；不能拿coord命中证明有字 |
| I06 | 浏览任务保留 | 配置15s墙钟、800ms单次滑动、max60；另有最终20次300ms滑动与1s间隔，二者不合并删除 |
| I07 | 入口确实离开首页 | 入口被遮挡仍在首页时按证据BACK补点，最多2次；持续失败rc4，不继续bag扫描 |
| I08 | 真实焦点门禁 | StatusBar/锁屏/陌生包/未知不允许业务点击/滑动/应用内BACK；底层PDD resumed不放行。WAKE/START/HOME/STOP等生命周期操作依独立白名单前置条件，不能借此绕过业务门禁 |
| I09 | 进度核实语义不伪报 | 数字下降/已完成文本/奖励文本/兼容弱证明分别有proof_kind；不都写成已观察数字下降 |
| I10 | 每日标记跳过 | 非force且当天marker存在，业务不接设备、不OCR、不通知；历史unit的预连接差异归D03 |
| I11 | 通知一次且不影响业务rc | endpoint缺失0次；配置后一次send attempt；无自动重试；标题无日期 |
| I12 | 账本不挡路 | 正常/已完成/lit2清0；pend读到N照抄，读不到有正数则减1，否则不写；不恢复暂停门禁 |
| I13 | lit2每天继续提醒 | lit2不写日标记，下一自然日继续检查和需人工通知，不能优化成终生只提醒一次 |
| I14 | 离线彻底无设备/网络 | replay/bench/check-config --offline不构造live适配器，不读端点，不发通知 |
| I15 | 变更设备结果未知不能盲重发 | 同ActionId最多一次底层动作；丢响应后先观察；不能自动重跑整链 |

## 3. 真实代码与文档矛盾 B01～B08

兼容答案以固定源码和oracle为准，不以一段简化说明替代。每条在测试中具名。

| ID | 实际源码行为 | 迁移决定 |
|---|---|---|
| B01 | 旧conf存在但不可读时load_ocr_conf回退默认；部分文档说rc78 | compat loader保留并记录warning；新TOML不可读失败，归D06 |
| B02 | 无效配置rc78不推送；cmd_run缺Tesseract rc78会推一次 | 按原因区分，旧缺OCR测试仍保留；不按rc78一概禁推 |
| B03 | 创建RUN_DIR失败可能返回73，公共表遗漏 | 增补73的运维语义和测试；新程序存储错误显式记录 |
| B04 | verify_light存在“文本定位点过、前后次数不完整也算过” | legacy保留LEGACY_TEXT_WITHOUT_COUNTER；v2首版也不偷偷收紧，报告证据不足 |
| B05 | rc0且lit0或lit3会最终滑动/写marker；文档称lit0失败 | compat特殊case保留；默认合法状态机不产生无终态成功；检测到此不可达路径必须显式INTERNAL状态，不静默换业务语义 |
| B06 | status执行adb devices；全局bootstrap会读push文件 | live status保留用途；新增offline路径不读端点，归D05 |
| B07 | 部分失败收尾会HOME；早期preflight失败直接返回，不同路径动作不同 | 按完整trace区分；不统一finally无条件HOME，lit2/4绝不能被finally覆盖 |
| B08 | 同名Activity不保证同页；focused_act未知可绕过“仍在首页”判断 | v2UNKNOWN显式阻断按D02处理；不再把“未知”解释成“已经离开首页” |

原始依据：[装载](../../pdd.sh#L316)、[核实末尾](../../pdd.sh#L1382)、[运行和收尾](../../pdd.sh#L1531)、[status](../../pdd.sh#L2030)。

## 4. 本次明确允许的工程变更 D01～D08

这些是重构规格的一部分，不由实现者临场决定。不要扩大成其它业务规则改动。

| ID | 变更 | 验收差异 |
|---|---|---|
| D01 | presence显式一次，搜索才有多轮预算；嵌套deadline封顶 | bag presence不再继承12轮；重试差分单列，不要求旧次数逐字相同 |
| D02 | 真实焦点、快照新鲜度、损坏输入、动作未知的统一门禁 | 旧程序可能误推进的观察变成UNKNOWN/有界失败；不得新增合法动作 |
| D03 | 所有live入口共用运行锁；日标记后才创建设备；移除unit无条件预连接 | 第二实例rc75、无设备动作；已标记不连接；timer触发规则保持 |
| D04 | 不可变工件、保存raw OCR、原子状态/journal、固定业务日期 | 新增日志/工件字段，防覆盖；写失败operational_status明确，不能虚报marker已写 |
| D05 | exact/reprocess/trace分开，offline模式能力隔离 | 旧缺TSV证据exact=INCOMPLETE；不把重识别当当时输出 |
| D06 | 新TOML严格校验、版本化profile/模型、缺所选引擎先停 | 新配置坏值/不可读/模型hash错在设备前失败；旧conf兼容不被悄悄改变 |
| D07 | 通知成功按传输+HTTP+JSON业务码判断 | 空body/非JSON/HTTP错误不再被子串误判成功；仍一次attempt、业务rc不变 |
| D08 | 真正懒执行/同帧共享/按页路由/主OCR后端切换 | winner变化需图像ground truth验证；不会因更快就豁免误点/误终态 |

band有区域外命中抑制pill、max-line confidence宽松规则、done额外限制、通知重试、减少浏览时长/最终滑动次数均不在默认变更列表。若以后要动，另建版本和验收，不夹带。

## 5. 终态与效果映射

| 场景 | rc/lit | marker | 账本 | 识别终态之后设备收尾 | 通知 |
|---|---|---|---|---|---|
| 当日marker已有，非force | 0/不强造lit | 已有 | 不改 | 零业务动作 | 0 |
| done普通字样 | 0/1 | 写 | 0 | STOP+HOME | PDD ✅ |
| done已使用 | 0/1 | 写 | 0 | STOP+HOME | PDD 已使用 |
| exchange | 0/2 | 不写 | 0 | 零动作、留在当前屏 | PDD 需人工 |
| 点亮核实通过 | 0/3 | 写 | 0 | 既有最终滑动，然后STOP+HOME | PDD ✅ |
| pend | 0/4 | 写 | 屏幕N/照账减/不写 | 零动作、留在当前屏 | PDD 💡 |
| 次数不变/坐标点且无法核实 | 6/见oracle | 不写 | 不以失败覆盖 | 旧失败路径HOME；若传输未知则仅尽力且记录 | PDD ⬛ 退出码 6 |
| 设备掉线/锁屏 | 2或3 | 不写 | 不改 | preflight不虚造动作 | PDD ❌ 对应原因 |
| 入口失败/后续定位失败/launch焦点非PDD | 4/5/7 | 不写 | 不改 | 对应旧路径；精确trace断言 | PDD ❌ 退出码 N |
| 缺adb | 69 | 不写 | 不改 | 零 | 0 |
| 配置invalid | 78 | 不写 | 不改 | 零 | 0 |
| 所选OCR不可用 | 78 | 不写 | 不改 | 零 | 有配置时一次“缺OCR”；保留旧缺Tesseract对应文案 |
| 无法创建状态/证据目录 | 73 | 不虚称写入 | 不虚称写入 | 动作前发现时零动作 | 本地报告为主，不因通知失败掩盖本错 |
| 第二个实例抢锁失败 | 75（新增） | 不改 | 不改 | 零 | 0 |

没有新增成功路径。业务成功但state_commit失败时，summary明确business_status与operational_status；CLI返回73，legacy业务rc另字段保留，通知不能写“marker已写”。这是D04的显式运维变化。

## 6. 47 个旧用例逐一迁移

所有ID保留。每个场景需要assert：完整有序device trace、通知attempt数/标题字节、marker、ledger、rc/lit、proof_kind及关键拒绝原因。下表简述不是全部assert替代品；精确答案由T01导出。

| # | case ID | 核心断言 |
|---|---|---|
| 01 | marker-already-done | 无设备/OCR/通知；D03移除unit预连 |
| 02 | no-tesseract | legacy profile rc78，0tap，缺OCR推送一次 |
| 03 | no-adb | rc69，零设备与通知 |
| 04 | device-offline | rc2，重连预算有限 |
| 05 | locked | rc3，不尝试密码 |
| 06 | wrong-foreground | rc7，无业务tap |
| 07 | shade-slashless-focus | StatusBar不能被PDD背景放行，旧cleanup与新D02差异显式 |
| 08 | bag-not-found | 主线bag坐标兜底仍存在，错误页面核实失败 |
| 09 | already-lit | lit1、marker、默认✅标题 |
| 10 | exchange-needs-human | lit2、账本0、不写marker、无额外动作 |
| 11 | happy-ocr | lit3、浏览与最终滑动均发生 |
| 12 | entry-swallowed-back | 仍首页触发BACK+重定位，不直接扫bag |
| 13 | entry-swallowed-stuck | 达入口上限rc4、没有bag盲点 |
| 14 | bag-right-slot | 右侧版式命中不被旧x界限拒绝 |
| 15 | browse-reenter-venue | BACK落频道后按证据重进、只归属一次BACK |
| 16 | browse-back-reads | BACK直达活动页，不多点bag |
| 17 | browse-band-psm6 | band6兜底横幅，实际进入浏览 |
| 18 | count-new-wording | 天内点亮措辞，6→5核实 |
| 19 | prize-take-coord | 奖励上下文允许原COORD_take；日志来源明确 |
| 20 | prize-take-ocr | 奖励上下文实际文字命中，不冒充坐标 |
| 21 | pend-proof-ok | 进度缺失但pend证明进入目标页，lit4 |
| 22 | pend-verify-4 | 点后pend映射4，不误报6 |
| 23 | pend-days-unreadable | 无N无可减账本则不写 |
| 24 | pend-days-1 | 屏幕1照抄1，不写0 |
| 25 | pend-days-roll | 无N、账3减为2 |
| 26 | pend-days-copy | 屏幕3覆盖账9 |
| 27 | pend-days-psm-fallback | psm6无天数后11读到，复用同帧 |
| 28 | used-terminal | 原done语义接住，不能light兜底再点 |
| 29 | used-band-psm6 | band6读已使用，不能丢recipe |
| 30 | recovery-coord-ban | 恢复坐标拒绝，不因预算优化放行 |
| 31 | happy-coord | 主线原坐标可用，后验核实仍必需 |
| 32 | happy-pill-band | pill精确recipe触发 |
| 33 | already-lit-pill | x1读done，lit1 |
| 34 | count-unchanged | 4→4不能说点亮成功，rc6 |
| 35 | count-unreadable-coord | 纯坐标且无核实rc6 |
| 36 | popup-rescue | 认到允许的关闭词才点，之后重观察 |
| 37 | carousel-wrong-frame | 不进正确页，证明上限失败 |
| 38 | xml-channel-hit | XML胜出；新程序对应目标OCR调用数0 |
| 39 | ledger-normal-zero | 账3不阻断，正常成功清0 |
| 40 | ledger-garbage-runs | 账乱码不阻断 |
| 41 | ledger-no-file | 不存在则正常成功建0 |
| 42 | ledger-already-lit-zero | 已点亮也清0 |
| 43 | conf-band-psm6 | 配置真的改变recipe调用，不能仅看最终lit |
| 44 | conf-unknown-key-stops | 旧名单外键rc78 |
| 45 | conf-bad-value-stops | BAND_SCALE=0拒绝 |
| 46 | conf-calibration-key-stops | 不因前缀宽放标定键 |
| 47 | push-metrics-in-log | HTTP/耗时来自真实fake响应；业务与发送结果分离 |

720×1280、1440×2560各47条。增加360、1080、非整数缩放和旋转的几何性质测试，但不能把合成resize当新设备真OCR验证。

## 7. 11 个原负对照 + 新故障

| mutant ID | 故意破坏 | 必须被哪条测试杀死 |
|---|---|---|
| browse-reenter-venue | 禁止按bag回活动页 | 同名case的动作/进度来源 |
| bag-not-found | 删除主线bag坐标 | 同名case明确缺动作 |
| prize-take-coord | 删除take坐标 | 对应take来源/动作 |
| used-terminal | 删除done救场 | used-terminal终态/动作 |
| used-band-psm6 | done recipe删6 | used-band-psm6识别来源 |
| used-title-split | 已使用标题改✅ | 精确UTF8标题 |
| lit1-title | 普通lit1标题改其它 | already-lit标题 |
| entry-retry-guard | 入口页证明恒假/漏检查 | 入口恢复动作/rc |
| focus-fail-closed | 无斜杠焦点与拒绝逻辑双破坏 | shade-slashless-focus禁止动作 |
| conf-not-loaded | 跳过配置装载 | conf-band-psm6必须真实进入浏览 |
| push-metrics | 删除HTTP/时间来源 | push-metrics事件字段 |

mutation结果必须为11执行、11杀死、0存活、0基础设施错误。修改未生效/导入报错/语法错不是kill。现代版本的负对照可改用受控策略fixture或语义mutation，不继续绑Shell行文本。

新增故障至少覆盖下表；每条期望reason_code、最多耗时、最大动作次数、状态提交与工件：

| 组 | 输入/时序 | 预期 |
|---|---|---|
| 截图 | 空/非空损坏/截断PNG/旧临时文件残留 | INVALID，无旧帧动作 |
| 层级 | malformed/空/旧XML+新图/耗时卡住 | 明确UNKNOWN/有界视觉兜底，不无限挂 |
| OCR | 缺语言/模型hash错/崩溃/超时/迟到结果 | 不当作没字；旧epoch结果只用于证据 |
| 几何 | tap≠PNG/旋转/中点舍入/ROI越界 | 验证变换或拒绝，不默认点0,0 |
| 文本 | 邀好友抽福袋/同屏两个同名/高置信无关字 | 框/上下文不会指向错误按钮；旧宽松规则可观察 |
| 焦点 | 空→有效、StatusBar但PDD resumed、subsidy点后通知栏 | 下一动作前真实检查，未知不当离开首页 |
| 恢复 | BACK退出PDD、两种落点、两个模块各自BACK | 无额外/重复BACK，按证据决定 |
| 输入 | 已发点击但丢响应、库内部重发、worker卡死 | UNKNOWN_EXECUTION、一次底层动作、无自动同意图重发 |
| 缓存 | 两key共享帧、新帧相同像素、缓存时间刷新、轮播自变 | 纯结果可复用，动作令牌不能复活 |
| 时间 | 墙钟前后跳、午夜跨日、嵌套重试重置deadline | monotonic受限、固定business_date |
| 进程 | 双run、run与point、旧新入口同时；Coordinator执行中SIGKILL后第二launcher；Guard也死亡 | 同设备lease保留到worker/native清理；重启quarantine检查未决效果，不能趁锁空再发动作 |
| 持久化 | intent后SIGTERM/点击后SIGKILL/证明后marker前崩溃/磁盘满；下一timer/force/跨日/回滚产生新ActionId | 未决逻辑效果跨运行索引，恢复先只读核实；新ID不能绕过阻断，不重复动作/虚报状态写入 |
| 通知 | DNS/TLS/HTTP5xx/200非JSON/空body/code非0/回复丢失 | 一次attempt、业务rc不变、delivery分型 |
| 隔离 | 真ADB绝对路径/继承ADB socket/PUSH_URL/HOME/未知命令 | 测试运行器阻断，不能靠只改PATH自称隔离 |
| 资源 | 模型反复加载/多线程同实例/队列无限堆积 | 计数门禁、实例独占、队列与LRU有上限 |

## 8. 真图质量门禁 Q

### 数据与标注

- manifest列每张原图/脱敏图SHA、日期/场次/layout、ground truth、允许锚点区域、不可点击目标、进度/天数、数据split。
- 逐类报告：HOME、遮罩HOME、频道左右bag、轮播无bag、ACTIVITY light/done/used/exchange/pend、BROWSE、PRIZE、UNKNOWN、StatusBar、同名邀请干扰。
- 每类目标至少5张独立来源、至少3天只是采集目标；缺失类必须出coverage gap，不能生成几张合成图冒充真实帧。
- 拆分按场次/日期/layout，hash/近重复防泄漏。仅在calibration调阈值，heldout不回填调参。

### 必报指标

1. 文本presence召回与误命中，按目标和页面分组。
2. 可执行定位：预测锚点落入人工标注允许区域，且未命中禁止动作区。presence成功但框不够精确不算click成功。
3. count/pending_days精确值与unknown率；不能把猜数作为正确。
4. terminal混淆矩阵，尤其错误成功/错误人工兑换/错误pending。
5. 引擎fallback率、每帧OCR次数、目标从采样到动作准备的年龄。
6. 数据量、日期范围、缺失类、脱敏影响、统计区间；零误点只描述本数据集，不外推零风险。

G4质量硬条件：heldout中新增禁止动作=0，新增误成功=0，人工兑换动作=0；原baseline能正确定位/读数/终态的样本不得无解释退化。允许有标注证明更正确的新winner，但每项差异必须列原图和原因，不能以“字更像”通过。

历史333帧/274负帧扫描的结果仅是当时整页词法scanner的结果。裁片/PSM/阈值会改变识别，不能推成完整级联误报上界；Q门禁必须跑实际全部生产通道。

## 9. 性能测量 P

### 比较profile

- P0：固定Shell基线（本地隔离重放，带真实Tesseract，不碰设备）。
- P1：Python legacy-parity/Tesseract。
- P2：Python/Tesseract，懒执行+同帧共享+统一预算。
- P3：single-device-v2，选定的主OCR/设备后端；候选包含RapidOCR与Maa底座时分别测量，不能同时隐式双跑。
- 传输PNG/JPEG/raw/minitouch等变体单列；质量变化与缩放映射必须先过Q。

### 方法

1. 同一Debian机器、相同帧/模型/hash/依赖与线程配置。记录CPU负载、温度/频率、内存、网络、图像尺寸。
2. 微基准热身后至少30组成对AB/BA交错运行；资源多候选随机区组，记录seed。便宜的纯函数可更多，不用30样本报p99。
3. 冷启动每次新进程，含解释器、依赖import、模型/session初始化到首个有效结果；热帧延迟单独报，禁止热帧成绩替代每日一次冷启动。
4. 固定完整场次/trace同时报总耗时；没有真机时，截图/动作延迟是模拟，不在online成绩里出现。
5. 真实日常试运行只用自然机会，各日状态不完全相同，报逐日数值和阶段组成；少量天数不计算有意义的p95可靠性结论。
6. 输出p50/p95/max、配对差值及bootstrap区间（注明相关场次），原始观测表可复算；未过门槛保留为失败报告。

### Span与计数

冷启动、设备连接/服务启动、焦点、PNG、XML、decode、preprocess、det、rec、Tesseract、匹配、状态判定、真实任务等待、动作执行、恢复、状态提交、通知、报告。

计数：模型加载数、host/device进程启动、截图/层级次数、OCR/recipe次数、fallback率、cache hit、retry、动作、bytes、RSS总和/峰值、CPU时间。父进程与worker全部纳入内存/CPU，不能只测Coordinator。

### 硬结构门禁

- 同capture/recipe/模型只识别一次；XML合法命中时该目标整页OCR=0。
- 正常一轮选中主模型每种加载≤1，online VisionWorker≤1；不因每个key启动worker。
- presence(bag)最多1次；seek(bag)才允许12次且受45s父预算。
- 每次设备动作最多1次底层调用；UNKNOWN不自动重发。
- worker hard timeout在deadline+1s回收窗口内生效；程序不继续派动作。
- retained decoded-image cache≤64MiB初值；运行期队列上限明确，不能无限缓存。

### 性能验收目标（设计值，尚未测量）

| 项目 | 目标 | 未达标怎么办 |
|---|---|---|
| 720p固定帧单观察热路径 | p95≤1.5s，质量先通过 | 看det/rec/预处理/调用次数，再改引擎或ROI |
| 主模型冷启动到可识别 | ≤5s目标 | 计入每日总成本；若略超但总体胜出，须ADR给出数字与理由 |
| 固定真实场次离线端到端 | 相对P0至少降低30%，配对差值无退化证据 | 不以换语言完成为理由豁免，继续优化 |
| 无恢复成功/已完成在线场次 | 初始总目标≤120s | 不删除15s浏览/20次滑动达标；真机样本不足标待验 |
| 一次轮播/允许恢复路径 | 初始总目标≤240s | 复查重复采集与错误页面识别，给出阶段账单 |
| 运行总deadline | 600s初值，通知≤15s、收尾≤10s | 受控结束，无整链自动重跑 |
| 总RSS | 首版目标≤512MiB | 用含worker的实测值；能耗/延迟更优而需超出时须ADR，禁止悄悄增加 |

30%离线改善与结构约束是晋升门槛；绝对120/240秒是待主机测量校准的SLO，调整必须引用基线与不可削减的任务耗时，不能为报告好看改分母或删失败样本。

## 10. 门禁与CI入口

未来统一命令（T02创建后有效；`scripts/verify.py` 是拟定入口）：

```text
uv run python scripts/verify.py --gate G0
uv run python scripts/verify.py --gate G2 --module device
uv run python scripts/verify.py --gate G3 --offline
uv run python scripts/verify.py --gate G4 --dataset <固定manifest> --output <本地目录>
```

| Gate | 退出0必须满足 |
|---|---|
| G0a | T00门禁自身反例全通过，47×2/11执行数准确，坏ONLY/超时/缺标记能失败 |
| G0b | 固定源码SHA、oracle、差异表、语料inventory存在且无凭据 |
| G0 | 上两项+公共schema/fake/依赖边界、Python安装测试通过 |
| G1a/b | 环境/引擎能力报告与语料manifest/split/缺口完整，不冒充质量通过 |
| G1c | T18a早期设备通道资格：采集/几何/冷启动/freshness/取消/重试与子进程清理过；在G4前完成，不领取业务奖励 |
| G2 | 各模块合同+自身测试通过，公共类型无漂移 |
| G3a | T14组合根、CLI兼容/offline能力与所有候选适配器合同接通；作为完整G3的预检 |
| G3 | 47×2、11mutation、故障矩阵、CLI/通知/状态/隔离全过；必要skip=0 |
| G4 | 完整级联Q条件、P结构与相对性能过；选型ADR+原始数据齐全 |
| G5a | release打包/离线安装/unit验证/模拟回滚通过，无生产动作 |
| G5 | 受控设备验证和自然日观察报告完成；未出现终态coverage明确 |
| G6 | 候选切换、状态兼容、回滚演练、下次timer核对与用户说明完成 |

CI分层：
- 每次PR：Ruff、mypy、公共合同、纯单测/47场景/fast mutations；offline网络隔离，Linux为主，几何/解析可加Windows smoke。目标常规测试≤60s，实际时限由基线设定。
- 视觉/模型/profile变更：必须跑完整固定真图和质量差分；按模型缓存key下载固定hash，测试时断网。
- G4基准：目标Linux主机的手动/受控job，不拿共享云runner成绩当这台机器成绩；无业务设备动作。
- 设备阶段：显式受控任务，只有一台设备锁，不随push自动触发真机。
- CI不持有真实推送/VLM端点；不得为CI写能给手机发通知的secret。artifact只上传脱敏数据。

机器结果schema至少：gate、version/source/config/model/dataset hash、expected/executed/passed/failed/skipped/infra_errors、durations、coverage_gaps、artifacts。必要项skip计为门禁失败/未完成，不用0跳过计数掩盖未执行。

## 11. 发布、回滚与中断恢复

目标release形状：

```text
~/.local/lib/pdd/releases/<release-id>/   # wheel/venv/模型引用/manifest，只读
~/.local/lib/pdd/current                 # 原子切换指针
~/.local/lib/pdd/last-known-good
~/.config/pdd/config.toml                # 私有可变配置，权限600
~/.local/state/pdd/                      # 状态/journal/锁兼容路径，不随release覆盖
~/Desktop/pdd.sh                         # 稳定兼容launcher
~/Desktop/pdd-runs/                      # 原证据入口保持可用
```

模型大权重可共享内容寻址只读目录，各release只引用hash；回滚时不能被新版覆盖同名权重。

发布步骤：
1. 构建和离线check候选，验证依赖/模型hash/状态schema兼容；先读旧状态的副本测试，不改真实状态。
2. 记录现役timer enabled/active、unit内容、主机业务时区、下一次触发、current与配置hash；只记录端点来源不打印值。
3. 在确定的维护窗口暂停timer，等待/协作停止当前run，确认worker已退出，持有维护锁。不要直接kill未知归属的ADB server。
4. 配置采用expand/contract：新reader先能读新旧schema，再启用新配置。旧conf不增加新键。
5. 原子切current到候选，保留已验证旧release和兼容配置；launcher一次解析路径并继承同一锁。
6. unit内容改变才daemon-reload；保持oneshot、Restart=no、原timer的10:00/180s/Persistent/home-lab语义。外部timeout按测量定，不用加长掩盖hang。
7. 恢复timer前核对Persistent是否将立即补跑及当天marker/UNKNOWN journal。需要只读核实的当天不立即强制再跑。
8. 自然日运行观察，只一个active executor；旧版只读存帧。汇报真实点亮、不同终态和未验证状态。

回滚触发：新增误点/误成功/重复动作、状态不可读、模型不兼容、无法终止的worker、严重性能退化。

回滚顺序：停timer→等run/worker退出→保留现场证据→原子恢复release+兼容配置→离线check→保留当天marker/账本/journal→按原日历恢复。不得恢复旧状态备份覆盖今天、不得回滚后自动run force、不得重复发未知结果的通知。

任何真实输入发生后，这一轮无法通过“回滚代码”撤销。重启只能核实已有结果；未知继续保持未知。

## 12. 交付核对单

- [ ] 公共合同、源码/模型/config/dataset哈希及变更表齐全。
- [ ] 47×2、11负对照、故障矩阵与隔离测试有可复算报告。
- [ ] 完整生产级联在heldout真图上过质量门禁，缺口明确。
- [ ] exact回放能看到当时原始读数，reprocess能对比当前结果。
- [ ] 性能分阶段账单、调用数、冷启动与峰值RSS齐全。
- [ ] 单设备锁和UNKNOWN_EXECUTION策略经丢响应测试验证。
- [ ] 自然日实际点亮覆盖、7个机会观察与其它终态覆盖说明。
- [ ] 配置/状态兼容、systemd下一次触发、回滚演练和用户操作说明完成。

清单未勾项就是未完成；不能用“难度大”“已经改成Python”或“日志看起来正常”代替验收。
