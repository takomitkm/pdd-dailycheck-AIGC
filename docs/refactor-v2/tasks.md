# 并行任务与交接规格

关联：[总规划](README.md) · [接口契约](architecture-contracts.md) · [验收规格](acceptance.md)。

本清单是重构执行合同；当前只交付规划。没有任何任务已经因写在清单里而完成。

## 1. 分工与合并规则

- 集成人唯一维护 domain 公共类型、contracts/、根工程配置、uv.lock、CLI 组合根和最终发布入口。
- 一个任务一个分支/worktree；从标有 contracts-v1 的共同提交开始。工作区若所有 agent 共用同一目录，只能按下表独占前缀写文件；推荐使用独立 worktree。
- 公共接口需要改动时，提交字段/语义/影响模块/迁移方法到集成人；先改契约与公共测试，再让相关分支同步。禁止某模块私建同名模型绕开契约。
- 每个任务拥有自己目录中的测试。tests/conftest.py、公共 fake、integration 场景注册表、golden 基线仅由集成人或明确的测试负责人修改。
- fixture 由 T01/T04 发布内容哈希快照；并行实现者不能在各分支修改标注来让自己通过。
- 每个 PR 至少包含：实现、模块测试、实际运行的命令/结果、未验证项、依赖版本变化请求。变更文档留在模块自己的 notes，不多人改总 README。
- 单设备 live 测试只有设备负责人可安排。其它任务交付全部可用 fake/固定帧验证。
- 用户追加 MaaFramework 后，T03-M/T06-M/T07-M 为正式候选子任务，定义见 [Maa 专项评估](maaframework-evaluation.md)。分别由性能/设备/视觉 owner承担，不新建第二套业务状态机。
- 不使用 `run force` 对同一天做新旧两轮验收。影子程序只能消费同一份已存 capture。

## 2. 看板总览

“依赖”是开始实现前的硬依赖；只有编写不依赖对方的设计/测试样例可提前。

| ID | 任务 | 负责人角色 | 依赖 | 独占写范围 | 门禁 |
|---|---|---|---|---|---|
| T00 | 修现有测试的退出码/计数/隔离 | 测试负责人 | 无 | sandbox/、现有测试运行脚本 | G0a |
| T01 | 基线与行为 oracle/语料清单 | 基线负责人 | 无 | legacy/、contracts/baseline/、tests/fixtures/manifest/ | G0b |
| T02 | 类型契约、工程骨架、公共 fake | 集成人 | T00,T01 | domain/、contracts/公共schema、根配置、tests/contracts/、tests/support/ | G0 |
| T03 | 环境/引擎/传输能力与性能小实验 | 性能负责人 | T02 | bench/probes/、bench/environment/、models/manifest候选草案 | G1a |
| T03-M | Maa离线能力探针/ADR-002草案 | 性能负责人 | T02 | bench/probes/maa/ | G1a；设备部分G1c |
| T06-M | Maa DevicePort适配 | 设备负责人B | T02,T03-M离线部分 | device/maa_backend.py及对应测试 | G2-B；纳入G3/G4 |
| T07-M | Maa VisionPort适配 | 视觉负责人C | T02,T03-M离线部分 | vision/maa_backend.py及对应测试 | G2-C；纳入G3/G4 |
| T04 | 固定真图标注与切分 | 语料负责人 | T01,T02 | tests/fixtures/public/、private-index/、annotations/ | G1b |
| T05 | 配置/profile/旧conf导入 | 配置负责人 A | T02 | config/、profiles/pdd/v1/、tests/config/ | G2-A |
| T06 | DeviceWorker/ADB/U2/动作适配 | 设备负责人 B | T02 | device/、tests/device/ | G2-B |
| T07 | VisionWorker/Tesseract/RapidOCR | 视觉负责人 C | T02,T03 | vision/、tests/vision/ | G2-C |
| T08 | 存储锁/日标记/账本/动作 journal | 持久化负责人 D | T02 | storage/、tests/storage/ | G2-D |
| T09 | 工件/事件/计时 | 证据负责人 E | T02 | evidence/、tests/evidence/ | G2-E |
| T10 | 通知渲染/单次HTTP | 通知负责人 F | T02 | notify/、tests/notify/ | G2-F |
| T11 | 纯状态机与上下文恢复 | 流程负责人 G | T02 | workflow/、tests/workflow/ | G2-G |
| T12 | 匹配器/事实解析/多目标观察 | 判定负责人 H | T05,T07；先用fake可在T02后开始纯匹配 | perception/、tests/perception/ | G2-H |
| T13 | exact/reprocess/trace/HTML报告 | 回放负责人 I | T02,T09；T12前先用fake | replay/、resources/、tests/replay/ | G2-I |
| T14 | CLI/组合根/旧命令兼容 | 集成人 | T05～T13，含可执行候选M子任务 | cli/、__main__.py、tests/cli/ | G3a |
| T15 | 47场景+故障注入/差分整合 | 测试负责人 | T14,T04 | tests/integration/、tests/mutations/ | G3 |
| T16 | 性能优化/后端晋升 | 性能负责人+模块owner | T15,T03,T04,T18a | bench/测量器；模块代码仍由各owner改 | G4 |
| T17 | release打包/systemd/回滚 | 发布负责人 | T08,T14；G4前可做fake演练 | deploy/、scripts/release/、systemd/候选模板 | G5a |
| T18a | 早期设备通道资格验证（不执行业务领取） | 设备负责人+集成人 | T03,T06,T06-M适用时,T14 | 本地生成reports，不改共享schema | G1c |
| T18b | 候选自然日试运行 | 设备负责人+集成人 | T16,T17 | 本地生成reports，不改共享schema | G5 |
| T19 | 切换发布/观察/旧入口退役 | 集成人 | T18b | 发布指针/兼容入口/运维说明 | G6 |

表中 src/pddcheck/ 前缀省略。不同角色可以由同一个人承担，但同一文件只有一个 owner；不用为了凑人数拆十几个 agent。

推荐 6～8 个并行执行者：A 配置；B 设备；C 视觉；D 持久化+证据；E 状态机；F 判定；G 回放+通知；集成人负责契约、CLI与门禁。T08/T09 或 T10/T13 合并角色时仍保持模块边界。

## 3. 逐步执行规格

### T00 — 先让测试结果可信

输入：固定旧提交下的 sandbox 与 scripts。不得先动生产判据。

步骤：
1. 将基线 sandbox 在本地 Linux 隔离环境运行，不再依赖 SSH 到签到主机；保留远程运行器作为显式选择。
2. sandbox 自身在 failed>0、选中用例不存在、执行数不符、基础设施错误时退出非零；ONLY 过滤返回所选 expected count。
3. 外层脚本启用严谨的状态传播，不让 tail、最后一个 echo 或 SSH 返回遮住 timeout/子命令失败；保留完整日志工件。
4. 使用唯一 mktemp 运行根。禁止共享 /tmp/pddsandbox/run；清理前检查绝对目标路径。隔离 HOME、环境和通知地址。
5. 桩遇到不认识的命令必须失败；阻断真实 ADB/网络/绝对路径可执行器泄漏。使用不挂手机/不暴露ADB socket的隔离环境，PATH 桩不是唯一屏障。
6. negative-control 聚合 executed/killed/survived/error；语法错/补丁没打上/超时不算 killed；11项缺任何一项失败。
7. A/B runner 确认两端执行成功、场次非零、帧数/读取数足够；逐项 DIFF/超时/两端同报错都不得算相等。

输出：可机器读的 harness-result.json，包含 schema、source_sha、case IDs、尺寸、expected/executed/failed/skipped/infra_errors、开始结束、工件引用。

完成：47×2、11负对照、错误 ONLY、故意断言错、强制超时、丢结束标记、未知桩命令均通过 acceptance.md 的门禁。baseline 未覆盖推送次数/完整动作序列的缺口明确标出，T15补齐。

### T01 — 基线与 oracle

1. 按本包 SHA 核对源，保存只读 legacy 快照和依赖信息。另记录所有实际 Shell 脚本版本，不能只抄 README md5。
2. 将 47 个 case 的输入、rc/lit、标记、账本、动作、通知、收尾导出为数据夹具；生成有序 effect trace，不只记 tap 次数。
3. 建立代码/文档差异表 B01～B08，按 acceptance.md；每条绑定源码与测试。
4. 用 fake 包装所有外部效果跑旧程序，记录 argv、次序、返回、文件写入和推送请求，不访问主机端点。
5. 列出实际可获得的真 PNG/XML/日志场次。7天窗口不存在的历史图标为缺失；仓库测量文本不是原图。
6. 发布 oracle version 和 annotation schema；未人工标注的旧程序输出只能当兼容答案，不能当真实世界正确答案。

输出：legacy/README、source-manifest、behavior-v1 数据、discrepancies、corpus inventory。完成：ID和计数可复核，基线只读、无密钥、不同尺寸行为可对比。

### T02 — 工程与公共合同冻结

1. 建立 src-layout Python 包、uv lock、dev dependencies、测试目录、入口，但不在包 import 时连接设备/读取端点。
2. 落地 architecture-contracts.md 中不可变类型、Protocol、几何函数、Deadline、错误分类、JSON schema。
3. 建立 FakeClock、FakeDevice、FakeVision、MemoryStore、RecordingNotifier、RecordingEvidence。fake 共享行为与真实端口合同，未知操作失败。
4. 样例：720/1440、裁片×2/×3、非整数缩放、真/假/未知焦点、损坏PNG、UNKNOWN_EXECUTION、lit2/4终态。
5. 设置依赖边界检查：业务模块导入第三方设备库、回放创建live factory、视觉发动作都会失败。
6. 固定变更记录 D01～D08、门禁名称和命令入口。G0 后打 contracts-v1 标签/提交。

输出：可安装的最小包、可运行公共测试、schema/JSON示例、接口hash。完成：序列化往返、fake/真实适配器测试规范一致、并行作者不需要改公共文件才能开始。

### T03 — 确认这台机器适合的执行器

离线部分先做：记录 Linux/Python/CPU flags/核心/RAM、可用 wheel、Tesseract语言、库版本；不读取凭据。固化模型下载/许可证/hash流程，预下载在安装阶段完成。

候选矩阵：
- RapidOCR：锁定小型中文det+rec，方向分类开/关分别评估；原图/目标ROI；线程1/2/4。
- 同模型 ORT CPU 与可支持的 OpenVINO CPU；不可用时记录原因，不在生产第一次初始化时才发现。
- Tesseract CLI 基线，必要时以独立候选评估 tesserocr，不能同时改 matcher。
- 传输验证归T18a/G1c：adbutils无损采集、U2层级、Maa选中截图/输入通道、焦点、显式启动/受控输入、hard cancel与新鲜度；不在离线实验里构造真Device。

必须给出冷启动+首帧与热帧分离的结果、CPU/RSS、质量结果；没有真图则只证明安装/接口可用，不给性能赢家。输出 ADR-001（锁版本/CPU引擎），其内容进入 uv.lock/model manifest 的修改由集成人完成。

### T04 — 固定真图语料

1. 原图只读复制到本地固定语料，hash去重、按日期/场次/layout分组；不依赖线上7天保留目录。
2. 覆盖首页带遮罩、正常首页、bag左右两版式/轮播无bag、活动页light/done/used/exchange/pend、浏览页、奖励浮层、陌生页、通知栏、同名邀请按钮。
3. 每帧标：页面、前台可知状态、允许/禁止动作、每个目标可接受点击区域、count/pending_days真值、明确不可读值、标注理由与来源。
4. 框必须是按钮/安全点击区域，不是照抄旧OCR预测框。允许多个等效锚点范围。
5. 真同屏渲染分辨率测试与合成resize分开。脱敏后重新验证涉及ROI的像素/识别结果；不能声称打码后与原图逐字节等价。
6. 切分 calibration/heldout，以场次/日期/layout分组，近重复不能跨组；最终保留每类的实际样本数。

目标每类至少5张独立来源帧，至少3个日期；缺类不编造，保留 synthetic 流程覆盖并标真图质量缺口。输出 dataset-manifest、labels、split hash、缺口表。涉及账号的原图保留私有目录，仓库仅放脱敏图或索引。

### T05 — 配置与 profile

移植默认别名/区域/坐标/阈值、旧conf逐键白名单和优先级，保留值来源。新增 TOML schema、profile引擎路由、预算和model manifest引用。

旧conf解析不 source/eval，不将新键写回共享旧conf。未知键/数值越界/凭据形态/文件路径错误分别测试；旧不可读conf实际回退行为保留在compat loader，新TOML不可读必须明确失败。

输出可公开的默认profile和旧配置只读转换报告；所有位置均使用单位明确的比例/像素类型。完成：bad config在设备构造前失败，profile可校验，无端点值打印；图像与点击坐标变换使用 domain 实现。

### T06 — 设备 worker

1. 先以fake server/协议夹具实现DevicePort；所有操作有hard deadline，超时可回收worker。
2. adbutils连接指定serial，不自动选第一台在线设备；无线重连、unauthorized、offline分别报告。
3. 原始PNG capture严格解码，层级和焦点独立时间戳；尺寸/旋转/read failure不拿旧值凑。
4. U2仅按需读hierarchy，关闭隐式等待/后台watchers；内部重试通过supervisor预算封顶。
5. focus解析保留StatusBar/锁屏/未知。显式HOME_ACT启动，禁止monkey兜底。
6. 单次动作走无隐式重发路径；丢响应、server重启、重复ActionId、旧epoch全部测试。
7. 连接/服务重建使epoch变化、作废未执行动作；worker结束释放连接。

完成：协议fake验证重复动作/deadline/失效语义；实际无损采集、服务、取消和新鲜度兼容性在T18a/G1c验证，再参与T16晋升。模块不访问通知/状态私有文件。

### T07 — OCR 与预处理

1. 先迁移现有Tesseract输出和recipe，保留stderr/exitcode/完整TSV/纯文本；验证语言包，不靠 `have tesseract` 一个布尔。
2. 预处理与逆变换统一实现，产物带原图hash/recipehash；一次crop多PSM共享。
3. VisionWorker复用解码图，结果缓存键按契约；一个引擎实例独占，超时回收进程组。
4. 接RapidOCR，明确检测/识别置信度与word/char/line几何能力，单行含多个按钮时不伪造子串点。
5. 缺模型/hash不符/字典不符/方向错误/截断/空读均可区分。
6. 在线lazy初始化，第一次需要才加载；若当前轮由XML/已标记即可完成，不加载不需要的模型。

完成：与旧recipe的固定输入输出兼容报告；Rapid challenger质量单独报告；同帧多目标不重复engine调用；版本/模型可精确重放。

### T08 — 运行锁与状态持久化

按契约实现StatePort、事务记录、日标记/账本兼容投影。全局绝对锁路径只按设备确定，run/point/probe/find/shot和迁移期旧launcher共用；锁不能在worker仍可能发动作时释放。

按契约使用薄LeaseGuard监督层持锁，Coordinator/DeviceWorker继承同一flock lease；旧launcher也走相同监督入口。Coordinator被SIGKILL时Guard与DeviceWorker仍保留锁；Guard回收整组/native子进程并确认退出后才释放。直接Python入口不能绕过Guard。测试Coordinator死亡时另一个launcher仍不能发动作，监督层同死时重启进入quarantine并检查跨日期未决效果。禁止wrapper和Python各拿一把互相等待的锁。

写入顺序：intent durable→receipt→业务结果durable→账本/marker兼容文件→commit receipt。崩溃可恢复已知结果，不重复未知动作/通知。中断、磁盘满、权限错、跨午夜、损坏账本、并发抢锁均有测试。

完成：能够区分业务成功但marker未写入；后续启动先读journal核实/导出，不能因此自动再点。状态schema具备前后版本兼容声明。

### T09 — 证据与计时

实现不可变artifact、JSONL事件、阶段span、版本manifest、summaryJSON和旧summaryTXT。每次reading保留raw输入输出引用、错误和变换信息。

durable action journal与普通高频计时日志分开处理：意图必须持久化，普通事件允许有界缓冲；先正确再用测量控制fsync频率。

完成：任一动作可追到依据帧/候选/判据，晚到OCR不改既有事件，seq稳定，工件冲突不覆盖。保留策略不删除固定语料/未解决journal，HTML相关内容已escape。

### T10 — 通知

标题和正文从RunOutcome纯渲染；精确比较UTF-8标题、发送次数、日期位置、pending原文/账本写入描述。HTTP只发送一次，受15s总deadline约束；失败/空body/非JSON/http非2xx/业务code非0分别记录。

配置无端点则0次发送；通知失败不改变legacy_rc。使用本地HTTP server/fake endpoint，不能拿真实端点作单测。HTTP严谨成功解析属D07，不混淆旧子串匹配兼容判据。

完成：任意请求体/异常日志不泄露端点，unknown delivery不重发，已标记跳过不会新发通知。

### T11 — 流程状态机

用FakeFacts+FakeClock即可开始。逐分支迁移do_step/proof_ok/verify_light/终态收尾，按上下文保留优先级，不以Activity名字替代页面证明。

重试计数和deadline存在RunState，locator不拥有重试循环。区分READ_ERROR/NO_MATCH、动作ACK/任务完成、UNKNOWN_EXECUTION/允许的业务恢复。

必须覆盖：入口被吞两次、bag3次证明、BACK两种落点、浏览15秒、最终20次滑动、prize take分支、exchange/pend后零动作、legacy文字弱证明。

完成：同一状态+事实+时间输出完全确定；不import设备库、网络、真实时钟/文件操作。预算修复D01与新freshness D02的期望值单独列。

### T12 — 定位与事实

移植norm/最长公共连续段/TSV合行/候选排序/region/坐标映射，保留原CONF的max-line兼容规则并显式标记；单独测试matched token低置信但其它token高置信的旧行为。

统一observe(capture,keys)：引擎读一次，候选按多key筛选。PageFacts保留UNKNOWN，不把bag文字等同频道页；不同workflow context调用不同纯判据。

输出legacy-parity和single-device-v2路由；Rapid几何不够用时调用精确recipe或拒绝点击，不用行框中点凑。完成：线上/replay调用同一函数，完整负例级联无新增危险命中，origin/proof都可审计。

### T13 — 回放与静态报告

exact不重OCR；reprocess重识别并标原结果与新结果；trace按序驱动同一状态机；旧证据导入时记录对齐不确定性，不能按最近文件名伪造同一采样时刻。

报告包含：运行结果、按阶段耗时、时间线、原图/框、原始文字、被拒原因、动作意图/回执/后验、当前与原版本差异。单文件HTML或本地资源均可，默认不加载远端JS。

完成：无ADB/no endpoint/no socket环境运行，--key可显式选择目标，无需改图文件名；缺OCR/缺关键帧返回INCOMPLETE且有统计。

### T14 — 接通CLI与旧入口

组合真实/fake适配器，校验→锁→读日标记→惰性worker→流程→commit→收尾→notify→report，早退也留下可解释结果。

兼容旧子命令和参数，新增check-config/doctor/replay modes。设备命令与offline命令构造不同能力集，不能依靠某个run-time布尔让所有模块都握着真Device。

完成：exit/title/summary/marker/ledger兼容映射可审查，69/78/73及新75明确，run force只跳过当日完成标记，不跳过焦点/锁/人工兑换界限。

### T15 — 整合门禁

将47场景改为fixture驱动，精确trace而非只断言次数；用FakeClock不真实sleep，测试不sed生产源。旧语义与D表差异分别验收。

扩展acceptance.md故障矩阵和11个mutation目标。依赖边界/能力逃逸测试必须真实失败；零用例、跳过必要case、mutant未执行都失败。

完成：G3机器报告，离线全套可并行、互不碰文件，真实OCR heldout与纯流程结果分开汇总。

### T16 — 逐项优化与晋升

顺序固定：惰性XML/PSM→同帧共享→裁片与解码缓存→显式presence预算→按页跳过无效XML→Rapid/CPU执行器→有界状态等待。

每项保留成对基准、调用计数、定位质量和语义差异。优化改动只能由相应模块owner修改自身代码；性能负责人不跨分支改共享文件。

完成：满足acceptance.md G4硬指标和设定SLO；没有统计证据的性能结论不得写“更快”。选择按冷启动到任务完成的成本，不按单个热帧吞吐量。

### T17 — 打包、安装与回滚

构建wheel、锁定依赖/模型、生成SHA manifest；release目录不可变。稳定launcher一次解析current路径后exec，不在运行中重新解析指针。

staging安装只用fake/离线check，candidate unit不被timer触发。systemd候选保留用户级oneshot、LANG、Nice、home-lab关联、无Restart；remove ExecStartPre连接是D03，连接搬进受锁且日标记之后的程序。

准备暂停/切指针/恢复timer/回滚脚本，Persistent补跑行为与当日journal一起核实。完成：假发布与回滚故障测试，不改现役timer。

### T18a / T18b — 早期通道资格与自然日业务验证

T18a在T14后、T16/G4最终后端晋升之前执行步骤1～3，只验证连接/采样/受控输入通道，不执行签到领取或兑换。输出G1c，实际backend/冷启动/取消/几何/freshness结论回填T03/ADR。T18b在T16与T17后执行步骤4～5，用自然日机会验证业务。这个顺序避免“先选择最快设备后端，后测设备后端”的依赖环。

1. 核实既有service/timer当前状态、业务时区和下一次触发时间，单执行器锁有效。
2. 进行一次受控维护安装/启动U2服务、只读截图/焦点/层级验证；记录这种“只读界面验证”包含设备服务安装/启动，不能伪装成零设备变更。
3. 原始PNG与旧PNG取证形状、tap空间、真实焦点、节点/截图偏差、响应丢失策略均完成验证；不为测试而领取/兑换。
4. T18b候选只占一次自然每日任务：以固定candidate release绝对路径的临时unit接管原自然时间槽，旧timer暂停且核实不会Persistent补跑；同时只有一个触发器。试运行不必先改变current生产指针。旧版只作存帧观察器，不点击、不通知、不写日标记；T19再将已验证release设为正式current并恢复唯一稳定timer。
5. 每天读报告，观察不同终态。没出现pend/exchange时，只能说synthetic/历史帧覆盖，不能声称真机覆盖。

完成：G5报告包含日期、真实样本数、未覆盖状态、阶段耗时、是否有UNKNOWN、一次通知结果。最低观察7个自然机会且出现过一次实际点亮；若都处于等待期，延长观察直到有实际点亮机会，不制造额外任务。

### T19 — 发布与维护移交

通过T18b/G5后完成一次原子切换，旧版本和可兼容配置保留；状态不回滚。记录下一次timer触发和current/last-known-good哈希。

旧Shell不再承担业务，但legacy离线oracle和测试保留到至少覆盖一个完整活动周期。给用户一页操作说明：改profile/查当日/精确回放/重识别/停timer/回滚/什么时候不能run force。

完成：G6、回滚演练和性能报告均存在；没有未解释误点/误终态/重复动作/契约偏差。若性能预算没过，任务继续，不能仅凭Python版能启动宣布完成。

## 4. 通用模块agent分派模板

```text
任务：Txx <标题>。仓库：<worktree绝对路径>。
先读 docs/refactor-v2/README.md、architecture-contracts.md、acceptance.md及本任务。
合同提交：<contracts-v1 sha>，oracle：<hash>，数据集：<hash>。
只允许修改：<write scopes>。不修改domain/公共schema/root配置/别人的fixtures。
公共合同有缺口时发字段级变更建议给集成人，先继续能独立完成的工作。
实现端口：<Protocol与方法>；必保留行为：<B/I条目>；本任务允许变更：<D条目>。
测试只用fake/固定帧；不SSH、不构造真Device、不读真实端点、不跑run/run force。
交付：commit、修改文件、测试命令和计数、未验证项、接口变更请求、性能数据（如有）。
不要因stub测试通过声称手机/OCR准确率已通过。
```

设备阶段另用专用任务说明，明确设备负责人、时间窗、现役timer状态和只允许的一次业务执行。

## 5. 合并批次与完成定义

1. Merge-0：T00/T01/T02，G0。所有分支rebase此提交。
2. Merge-1：T05、T06、T07、T08、T09、T10、T11；每个分支自带模块测试。集成人改lockfile一次解决依赖。
3. Merge-2：T12/T13/T14，接通完整legacy profile，随后T15 G3。
4. Merge-3：先T18a/G1c早期通道资格，再T16优化；每项独立提交与报告，G4通过后确定最终默认后端。
5. Merge-4：T17打包与回滚，T18b自然任务观察，T19切换与移交。

任务done：代码实现 + 公共合同兼容 + 对应门禁真实通过 + 产物可查 + 未验证项明确。Teammate处于inactive、工具返回0、日志打印OK、生成一个报告文件，都不能单独当done。
