# MaaFramework 专项评估与接入规格

更新：2026-11-05，回应用户追加的参考项目 [MaaXYZ/MaaFramework](https://github.com/MaaXYZ/MaaFramework)。这是前面[总规划](README.md)的一部分，继续服务于单台手机的模块化重构，不替换原目标。

## 1. 结论与采用范围

**MaaFramework 是正式的一等候选，应优先验证其原生控制器和 OCR 底座。Python 继续承担唯一业务状态机；Maa 可以替换设备/OCR适配器，不必把业务全部改写成 Pipeline。**

之前“更偏游戏/固定图像，所以不作为本项目候选”的排除不充分，撤回。它不是只能用于游戏或模拟器，也不是只能固定分辨率。旧讨论中的百分比迁移估算不作为这次计划依据。

明确决策：
- 架构现在确定为 Python 业务策略 + DevicePort/VisionPort + 不可变证据 + 单设备执行器。
- T03-M 优先实现 Maa 控制器、Maa OCR 两个独立探针；可以只采用其中一个，不要求整套捆绑。
- 生产默认按下述门禁决定；没有在本机测过之前，不把 Maa/ORT/RapidOCR 任一个写成已知最快。
- 只保留一套生产业务流程，禁止“Python recovery + Maa Pipeline recovery”两套各自点手机。
- 默认不迁移到完整 Pipeline，不引入通用 GUI/AgentClient/常驻 WebUI；它们不是单台每天一次运行的必要条件。

## 2. 研究版本与来源

官方主分支快照：`f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef`。本次研究另核对发布版 v5.15.0 的 Python post_recognition 接口。下面深层源码事实主要来自该主分支快照，不宣称全部已在 v5.15.0 本机验证。

| 内容 | 固定来源 |
|---|---|
| 控制方法 | [2.4-ControlMethods](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/docs/en_us/2.4-ControlMethods.md) |
| API/控制器选项/调试 | [接口概览](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/docs/en_us/2.2-IntegratedInterfaceOverview.md) |
| Pipeline机制 | [Pipeline协议](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/docs/en_us/3.1-PipelineProtocol.md) |
| Python扩展 | [Custom/Agent](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/docs/en_us/1.3-Custom%26Agent.md) |
| Python独立识别 | [v5.15.0 tasker.py](https://github.com/MaaXYZ/MaaFramework/blob/v5.15.0/source/binding/Python/maa/tasker.py) |
| 事件回调 | [Callback协议](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/docs/en_us/2.3-CallbackProtocol.md) |
| OCR模型加载 | [OCRResMgr.cpp](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/source/MaaFramework/Resource/OCRResMgr.cpp) |
| OCR错误/框 | [OCRer.cpp](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/source/MaaFramework/Vision/OCRer.cpp) |
| 同帧批量识别 | [PipelineTask.cpp](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/source/MaaFramework/Task/PipelineTask.cpp) |
| 截图重连策略 | [AdbControlUnitMgr.cpp](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/source/MaaAdbControlUnit/Manager/AdbControlUnitMgr.cpp) |
| 输入选择 | [InputAgent.cpp](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/source/MaaAdbControlUnit/Manager/InputAgent.cpp) |
| Shell输入成本 | [AdbShellInput.cpp](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/source/MaaAdbControlUnit/Input/AdbShellInput.cpp) |
| 控制器回放 | [ReplayController.cpp](https://github.com/MaaXYZ/MaaFramework/blob/f5d2f0f7f68a75e12455c37e3f9f4e3602d1bfef/source/MaaReplayControlUnit/ReplayRecording/ReplayController.cpp) |
| 官方OCR模型目录 | [MaaCommonAssets/OCR](https://github.com/MaaXYZ/MaaCommonAssets/tree/main/OCR) |

本次网络读取部分原始URL有临时失败/公共API限流，专项审查通过GitHub页面补读。未使用用户GitHub凭据，未安装SDK、推送二进制或连接手机。

## 3. 对本项目真正有价值的部分

### 3.1 单设备控制器

- ADB controller接收adb_path/address，真机无线ADB可作为候选。
- Encode/EncodeToFileAndPull/RawWithGzip/RawByNetcat是可评估的无损通道；MinicapDirect/Stream为JPEG有损；模拟器Extras加速不适用于这台ZTE。
- 控制器支持原尺寸与长短边等缩放，并回映触摸坐标；本项目初版显式use_raw_size，避免框架缩放后又被domain乘一次比例。
- Maatouch/Minitouch可能减少反复调用adb shell input的成本；部署/启动手机端二进制、ABI兼容和本轮初始化均要计时。
- 输入方法按优先级找可用方法，不等于测出最快方法；截图方法的测速选择也不能替代端到端基准。
- AdbShell fallback仍会启动adb子进程，因此可能输给当前计划中adbutils的socket调用。必须记录实际选中backend，禁止报告“Maa”却不报它实际退到哪个输入通道。

### 3.2 视觉与编排

- 本地OCR使用PaddleOCR转换模型，主分支实现走FastDeploy/ORT，session按模型缓存、懒加载。官方模型目录有多代，不是自动任选最新版就会最好。
- 支持ROI、expected正则、replace、阈值、排序、only_rec等。对已知紧框按钮，only_rec可能避免整页检测成本，须测量是否漏字/混淆背景。
- Pipeline有有序next、首次命中、on_error、命中次数、稳定等待、重复等机制；主分支还有跨同帧多个OCR节点的lazy batch共享，不可声称Maa每个目标必然重跑整页。
- Python有CustomRecognition/CustomAction；XML不是现成内置定位器，但能在Custom或独立适配器中接入。不是“完全不支持XML”。
- full-code有post_recognition(type,param,image)/post_action，业务可留Python，不必用完整Pipeline。

### 3.3 调试和证据生态

- 识别有all/filtered/best/raw_detail/debug图，事件有task/node/reco/action ID与sink；有日志、画框、错误保存。
- 有RecordController/ReplayController，能借鉴操作记录与底层模拟。
- MaaDebugger、VS Code插件、MaaLogAnalyzer等可作开发端工具。对于只有Python外部策略的路线，它们可显示框架内部任务/控制器事件，不会自动理解本项目所有业务状态，需事件关联与本地报告。

## 4. 必须补的合同缺口

| 发现 | 接入条件 |
|---|---|
| 截图内部可多轮重试、重连，甚至kill_server | worker hard deadline和子进程清理测试；禁止影响其它ADB客户的无边界server reset，必要时配置/受控补丁隔离 |
| Pipeline timeout是识别循环预算 | 继续使用项目的绝对monotonic截止时间和进程监督，`.wait(timeout)`返回不等于底层停止 |
| action success只是控制器结果 | 仍需PDD进度/终态后验、意图journal和UNKNOWN_EXECUTION |
| repeat>1/on_error会影响动作次数 | 业务输入repeat=1，禁止错误分支盲重点；不同时跑Pipeline自动恢复与Python恢复 |
| OCR推理失败可记录后返回空 | 不能直接把所有空结果映射ABSENT；需可靠错误状态桥接，或把无可判定的空结果标UNKNOWN再走可信fallback。不能靠猜日志字符串假装已解决 |
| OCR框是文本块矩形 | 标LINE精度；匹配子串不产生虚假字框，必要时tight ROI/旧recipe |
| cached_image是已解码且可能缩放数组 | 记录像素hash、raw-size、真实几何与色彩；允许无损raw→canonical PNG，不宣称收到原始ADB PNG |
| 回调可能多线程，停止可能没有terminal回调 | 快速入有界线程安全队列，由coordinator顺序写事件；缺结束是UNKNOWN，不是“从未开始” |
| Record动作完成后才落记录 | 不能代替动作前durable intent |
| Replay当前click/swipe不核坐标、会sleep原cost，未消费完可abort | 项目exact/trace和完整坐标trace测试仍保留；MaaReplay只作附加协议验证 |
| Python bind公共签名要controller | 无设备OCR初始化路线要实际验证，不能假定resource-only在Python已可直接用；可评估离线Custom/Dbg controller，绝不可绑定真手机来跑离线测试 |

所读输入层未见与U2相同的自动click重放，不代表有Android端exactly-once。断连/回复丢失仍按未知执行处理。

## 5. 三种路线的明确取舍

| 路线 | 收益 | 成本/限制 | 本次决策 |
|---|---|---|---|
| 全Maa Pipeline + Python hooks | 低代码、可视化编辑/调试、内建ROI批处理/稳定等待 | 业务进度、账本、动作未知仍要Custom；容易形成两套恢复状态 | 不作为首轮迁移目标；留独立原型比较，不先写全套 |
| Python状态机 + Maa设备/OCR适配 | 保留业务可测性，同时利用原生输入/视觉和事件 | 必须补错误语义、deadline、焦点、几何/离线绑定 | 优先验证的一等候选；设备/OCR分别裁决 |
| Python + adbutils/U2 + RapidOCR/旧Tesseract | 错误和类型适配直接，候选基线清晰 | 自己维护观察/缓存/报告；U2存在输入重放默认 | 基线与生产回退；不因已写草案而强保此组合 |

可最终出现“Maa Maatouch输入 + adbutils无损截图/焦点 + RapidOCR”或“Maa截图/输入 + MaaOCR + 旧Tesseract特例”。但每个运行profile显式固定一种路由，一个DeviceWorker统一拥有所有设备访问，不是多个框架各起后台自动点。初始化前降级、同帧OCR兜底、动作发出后失败是三种不同策略：前两者按固定路由允许，已发动作结果UNKNOWN时绝不能换transport/新ActionId再发；跨运行未决效果由StatePort阻断。

## 6. 加入任务图的三个子任务

### T03-M：Maa能力/性能探针

owner：性能负责人；依赖T02，离线结论进入G1a。实际设备部分在T18a/G1c，必须先于T16/G4最终裁决；最终ADR-002在G4汇总。

离线先验证：Python/native包、CPU架构、模型加载、显式image识别、无手机初始化方式、BGR/RGB、OCR错误/空结果区分、文本块/ROI坐标、callback队列和冷启动/RSS。

T18a早期通道资格阶段再测：各可用无损截图、选中输入方法、Maatouch初始化/权限、受控tap/swipe/key含丢响应/超时、取消/进程回收、是否尝试kill共享ADB server、raw-size回映。T18a不执行业务领取，结果必须先于T16/G4的最终设备后端晋升。

输出ADR-002，分别选择controller与OCR；不能只给一个“采用Maa”的总开关。

### T06-M：DevicePort的Maa适配器

owner：设备负责人；依赖T02、T03-M离线探针，合同门禁G2-B并纳入G3/G4，实际设备资格在T18a/G1c。精确写范围 `src/pddcheck/device/maa_backend.py`、`tests/device/test_maa_backend.py`（或同名子目录，T02冻结）。

遵守原DevicePort，worker内持有选定controller；动作前focus仍通过真实窗口读；默认raw-size，候选像素→touch映射一次。所有动作禁止Pipeline重复策略。原生DLL/子进程卡死必须被supervisor处理，回收确认前不释放设备锁。

### T07-M：VisionPort的Maa OCR适配器

owner：视觉负责人；依赖T02、T03-M离线探针，合同门禁G2-C并纳入G3/G4。精确写范围 `src/pddcheck/vision/maa_backend.py`、`tests/vision/test_maa_backend.py`。

识别使用显式传入的immutable image，不能从控制器cached_image偷偷取另一时刻。模型/字典/threshold/only_rec等参数版本化；返回engine_id=maa_ocr与LINE精度、原始detail和明确error。无法满足错误合同则该OCR候选不能晋升，设备候选仍可采用。

Maa SDK若需要资源目录，放release内固定版本，profile生成由配置owner负责。callback桥接在适配器局部，不改公共RunEvent格式。

## 7. 晋升规则：谁更适合单台就用谁

顺序：
1. 硬门槛先过：人工兑换0、误成功0、heldout无新增危险锚点、禁止动作0、一次意图一次输入、真实焦点、deadline可终止、离线不连手机。
2. 同模型/同原图先比较OCR执行器；另测框架默认模型/参数的完整路线，避免把模型差异冒充C++/Python差异。
3. 同一设备观察路径比较冷启动、截图、触摸、XML、错误恢复、峰值RSS和整轮cold-to-done；Maatouch服务初始化算进冷启动。
4. 采用有确定收益的组件。若总时间配对改善≥10%且质量不退化，优先该组件；差异落在噪声/区间重叠时，选择错误语义更完整、额外桥接更少的组件，默认回到已通过的基线。
5. 组合后的最终profile仍须通过G4相对原Shell≥30%的目标和G5自然日验证；单个组件胜出不代表整套已达标。
6. 若只读错误映射、hard cancel或框精度存在未解决缺口，记录淘汰原因，不为使用框架而放宽合同；可在不改变业务接口的受控适配补丁中修正后重测。

Maa与Python都不是凭名字获胜。确定的是单台架构、业务不变量和裁决程序；具体截图/输入/OCR默认值由这台手机和主机的报告给出。后端决策不需要用户再逐项选技术细节，执行者按此规则产出ADR并继续推进。
