# 架构与接口契约 v1

状态：规划中的公共合同。T02 将本文件落成代码和 schema，并锁定 contracts-v1；所有并行分支从同一合同提交起步。实现细节可以在模块内优化，公共字段和语义必须走变更记录。

关联：[总规划](README.md) · [任务分派](tasks.md) · [验收规格](acceptance.md)。

## 1. 系统边界与依赖方向

```text
cli/bootstrap
  ├── config -> domain
  ├── workflow -> domain / ports
  ├── perception -> domain / vision port
  ├── device -> domain / device port
  ├── storage -> domain / state port
  ├── evidence -> domain / evidence port
  ├── notify -> domain / notification port
  └── replay -> domain / perception / workflow / evidence（无 live factory）
```

- domain 只依赖标准库。它不 import adbutils、uiautomator2、RapidOCR、Pillow、HTTP、文件系统业务适配器。
- workflow 依赖 Protocol，不依赖具体设备/OCR/存储类；只有 cli/bootstrap 创建真实适配器。
- perception 是共享判定入口；线上、精确回放、重识别都调用它，禁止复制一份 replay_find。
- 适配器不得自行从环境读取参数，不互相 import 对方实现。所有配置在启动时规范化后注入。
- 没有任何视觉引擎拥有点击权限；它只产出候选。唯一 ActionExecutor 做动作校验，唯一 DeviceBroker 发设备变更。
- 通知模块不改变 RunOutcome；存储提交错误单独表示，不冒充签到失败/成功。

## 2. 运行模型：并行开发、串行设备

在线一个运行实例由三个受控进程组成：

1. Coordinator：运行锁、配置、纯状态机、事件与原子状态提交、通知、报告。
2. DeviceWorker：唯一设备后端所有者（Maa 控制器或 adbutils/U2 组合），按请求串行执行；持有连接、层级服务状态，不接收任意 shell 字符串。
3. VisionWorker：唯一在线 OCR 所有者（Maa OCR 或 RapidOCR/兼容 Tesseract），按需启动、每个模型一次初始化，复用 Pillow/NumPy 图像与推理 session。候选不自动全部加载。

不为每个 key/帧启动 Python；worker 仅在本轮任务期存在，不建设 24 小时主机 daemon。正常路径每个 worker 最多启动一次。只读 worker 崩溃允许一次重建；设备动作一旦进入执行未知状态，不靠重建 worker 重发动作。

IPC 首版采用带 schema_version 的有界消息和本地不可变工件路径，不用任意 pickle 载荷作外部协议。每帧落一份canonical PNG：ADB PNG保留收到的字节；Maa无损raw像素确定性编码为PNG，并另记原transport/色彩/像素hash。VisionWorker每帧最多解码一次。无需先建设共享内存或分布式消息队列。

DeviceBroker supervisor 给每个请求 hard timeout；超时终止/回收对应 worker 后才能释放设备锁。Python Future.cancel 或 thread timeout 不算终止底层调用。设备端已发出的操作无法靠杀主机进程撤销，必须记录 UNKNOWN_EXECUTION。

并行只用于：隔离的离线测试、不同历史帧的批量基准、代码开发。在线设备请求不并行；同一个 OCR engine 不并发调用；候选不能按“谁先返回”决定点击。

## 3. 公共数据模型

所有对象用 frozen dataclass 或等效不可变模型，跨进程 JSON 严格 schema。顶层 schema_version 从 1 开始。枚举值为稳定英文字符串，日志显示中文由报告层负责。

### 3.1 标识与时间

| 类型/字段 | 合同 |
|---|---|
| RunId | UTC 时间戳含微秒 + 随机后缀，跨进程唯一；不使用只有 HHMMSS 的目录名作 ID |
| CaptureId / ObservationId / DecisionId / ActionId | run_id 内唯一、有序关联；引用必须存在；ActionId 在实际调用前持久化 |
| release_id / config_hash / profile_hash / model_hash | SHA-256；不能只用行数、mtime 或可变模型名 |
| monotonic_ns | 超时、经过时间、等待、采集跨度；系统墙钟跳动不得延长截止时间 |
| wall_time | 带时区 RFC3339，用于人看日志；不参与重试预算 |
| business_date | 运行锁取得后固定一次；T01 核实业务时区，默认候选 Asia/Shanghai；不能跨午夜把同一轮写成两天 |
| state_epoch | 每次可能改变画面的动作提交前递增；同一 capture 的候选绑定此 epoch |

业务时区与 timer 本机时区的对应关系写入安装报告。当前对话的 Asia/Taipei 不能代替对 Linux 主机时区的确认。

### 3.2 错误不是“没找到”

```python
ReadStatus = OK | ABSENT | UNAVAILABLE | INVALID | TIMEOUT
ExecutionStatus = ACKNOWLEDGED | REJECTED | UNKNOWN_EXECUTION
CoordinateSource = XML | OCR | TESSERACT_PAGE | BAND | PILL | CONFIG_COORD
# OCR 必带 engine_id（maa_ocr/rapidocr）、engine_version、model_hash；不锁死某SDK。
BoxPrecision = GLYPH | WORD | LINE | ELEMENT | CONFIG
PageKind = HOME | SUBSIDY_CHANNEL | ACTIVITY | BROWSE | REWARD_OVERLAY | UNKNOWN
WindowKind = APP | STATUSBAR | KEYGUARD | FOREIGN | UNKNOWN
TerminalKind = NONE | DONE | EXCHANGE | PENDING
```

- Reading[T] = status、value（OK 时必有）、error_code、stderr_ref、duration_ns、attempt_count。
- 空 XML/空文本可以是 OK 但没有候选；解码坏 PNG、OCR 进程崩溃不能伪装成空结果。
- FocusState = window_kind、focused_package、focused_activity、window_label、resumed_package（可选诊断）、sampled_ns、raw_ref。
- 只有focused_package为PDD且window_kind=APP才满足业务TAP/SWIPE/应用内BACK的焦点条件；后台resumed_package=PDD不能覆盖STATUSBAR。WAKE、DISMISS_KEYGUARD、显式START、STOP、HOME是独立生命周期意图，按设备状态/目标包白名单校验，不要求尚未启动的PDD已在前台；它们不能携带业务点击坐标。关闭系统通知栏等特殊导航须具名策略与trace测试，不能用通用BACK绕过门禁。

### 3.3 Capture：画面与来源

Capture 至少包含：

```text
schema_version, run_id, capture_id, state_epoch
capture_started_ns, capture_finished_ns
png_ref?, png_sha256?, pixel_sha256?, screenshot_width?, screenshot_height?
xml_ref?, xml_sha256?, xml_sampled_ns?
focus_before, focus_after, tap_width, tap_height, rotation, display_id
screenshot_encoding, capture_transport, component_statuses
```

- 采集必须来自已验证的无损像素通道。ADB传来PNG时完整解码并保留原字节；Maa传来无损raw/已解码数组时记录transport/原编码/色彩/尺寸，以确定性设置编码canonical PNG并记录pixel_sha256。原传输字节可另存。JPEG转PNG仍是有损来源，不满足默认profile的无损门禁。
- XML、截图和焦点不是原子同时获得。必须记录各自采集时间与跨度；不能把它们叫成系统保证的同一瞬间。
- `capture()` 可以只请求 focus 或 PNG，`enrich_xml()` 给同一观察附加一个带独立时标的样本；超过可配置时间跨度/发生 epoch 变化，重开 Observation，不篡改旧对象。
- 初始 capture 最大允许跨度为 1000ms 目标值，实际可用界限由 T03 测量；超过时标为 COHERENCE_UNCERTAIN，允许离线报告，不能直接凭该组合执行动作。
- tap 空间与截图空间分开建模。旋转、尺寸、display 变化产生新 capture，旧坐标令牌失效。
- 第一版不做自动改 wm size/自动旋转校正。检测变化后选择经过验收的 profile 或退出，并记录具体原因。

### 3.4 几何、OCR 与候选

| 对象 | 字段/规则 |
|---|---|
| Rect / Quad | 坐标系名、x/y 值、有效范围；默认像素矩形为左闭右开，不允许未标注的 0..1/像素混用 |
| ImageTransform | 原图尺寸、crop 原点、padding、scale_x/y、旋转；能逆变换到原截图，再到 tap 空间 |
| RecipeSpec | recipe_id/version、ROI、颜色模式、阈值、缩放、OCR PSM/语言、引擎参数；规范序列化后参与 hash |
| TextToken | raw_text、normalized_text、box/quad、box_precision、confidence_raw、confidence_scale、char_spans（可选）、reading_ref |
| Candidate | key、matched_text/span、candidate_id、capture_id、epoch、source、match_overlap、engine_confidence、tap_point、box、recipe_id、rank_in_pass、rejection_reasons |
| LocateResult | MATCH / NO_MATCH / READ_ERROR / TIMEOUT，winning_candidate?、ordered_candidates、reads、duration_ns |

重要：match_overlap 是最长公共连续字符段长度，不是 LCS 子序列，也不是概率。Tesseract 的 0..100 与 RapidOCR 的 0..1 不能混成一个阈值或直接相加。

旧 TSV matcher 给每个字映射的是其所在 TSV word 的框，不是真实字形框；迁移时标记 WORD 近似。RapidOCR 首先验证受锁版本的 word/character boxes；只有整行框且一行包含多个按钮时，不能用字符数等分制造“精确字框”。可继续对紧 ROI 识别或调用原 recipe。字符框能力是 T07 的门禁，不是直接启用 `return_single_char_box` 就算验证完成。

legacy-parity 的 winner：先通道优先级，再该通道稳定排序和原始行序，取第一个 in-region；禁止全局最高置信度替换。band 与 pill 的触发条件也先照旧：band 未产生 hit 才试 pill；“有 hit 但都在区域外”是否允许补 pill 是独立语义变更，不混进迁移。

舍入分两类：配置比例点沿用原 `int(f * W + 0.5)` 正数规则；matcher 输出沿用变换后 `int(...)` 的截断规则。不得用 Python round() 统一替代；中点、边界、双分辨率和非整数缩放均有测试。

### 3.5 Observation、Decision、Outcome

Observation：observation_id、capture、按需共享的 readings、key->LocateResult、页面事实、终态事实、count?、pending_days?、origin、profile_hash、created_ns。

- 页面是推断，不是 Activity 名等价物。NewPageActivity 可同时表示活动页、频道页、旧订单页。
- Activity 的“已进入”判据优先保留当前 progress / pend / done 证明；不能为了状态机整洁强加用户已经否决的“已使用”第二约束。
- 同一 capture 的 count、done、exchange、pend 共享候选池，但根据 workflow context 保留优先级：进入证明阶段 count→pend→done；点前 done→exchange→pend→count；点后按当前 verify_light 对应分支。不能用统一全局排序覆盖这些上下文。

Decision：decision_id、input_observation_ids、previous_state、next_state、proof_kind、allowed_action?、terminal?、reason_code、retry_policy_ref。

RunOutcome：business_status、legacy_rc、legacy_lit?、proof_kind、last_screen、done_word?、pending_line?、pending_days?、marker_policy、ledger_policy、close_policy、notification_spec?、operational_status。

proof_kind 至少包括 COUNTER_DECREASE、DONE_TEXT、PRIZE_TEXT、PENDING_TEXT、MANUAL_EXCHANGE、LEGACY_TEXT_WITHOUT_COUNTER、NONE。兼容期保留旧弱证明分支，但必须记录真实 proof_kind，不写成“数字已经变小”。

business_status 与 operational_status 分离。通知失败不改变签到 rc；写标记失败、证据存储失败必须可见，也不能把它们冒充进度失败。

## 4. 公共接口：由 T02 实现同名 Protocol

以下是方法合同，类名/参数名由 T02 原样固定；类型定义一并落地，不由各分支补本地同名类型。

```python
class Clock(Protocol):
    def monotonic_ns(self) -> int: ...
    def now(self) -> datetime: ...
    def wait(self, seconds: float, deadline: Deadline) -> None: ...

class DevicePort(Protocol):
    def health(self, deadline: Deadline) -> DeviceHealth: ...
    def capture(self, request: CaptureRequest, deadline: Deadline) -> Capture: ...
    def enrich_xml(self, capture: Capture, deadline: Deadline) -> Capture: ...
    def execute_once(self, intent: ActionIntent, deadline: Deadline) -> ActionReceipt: ...
    def close(self) -> None: ...

class VisionPort(Protocol):
    def health(self, spec: EngineSpec, deadline: Deadline) -> EngineHealth: ...
    def recognize(self, capture: Capture, recipe: RecipeSpec,
                  deadline: Deadline) -> TextReading: ...
    def close(self) -> None: ...

class PerceptionPort(Protocol):
    def observe(self, capture: Capture, request: ObserveRequest,
                deadline: Deadline) -> Observation: ...

class EvidencePort(Protocol):
    def put_artifact(self, data: bytes, spec: ArtifactSpec) -> ArtifactRef: ...
    def emit(self, event: RunEvent, durable: bool = False) -> None: ...
    def finalize(self, outcome: RunOutcome) -> ReportRef: ...

class StatePort(Protocol):
    def acquire(self, device_id: str, deadline: Deadline) -> RunLease: ...
    def load(self, business_date: date) -> DailyState: ...
    def load_unresolved(self, device_id: str) -> tuple[UnresolvedEffect, ...]: ...
    def record_intent(self, intent: ActionIntent) -> None: ...
    def record_receipt(self, receipt: ActionReceipt) -> None: ...
    def commit(self, outcome: RunOutcome) -> CommitReceipt: ...

class NotificationPort(Protocol):
    def send_once(self, request: NotificationRequest,
                  deadline: Deadline) -> DeliveryResult: ...
```

纯函数由 workflow 拥有：`transition(state, observation, receipt, context) -> Decision`。只有 coordinator 把 Decision 转成 ActionIntent；transition 无 IO、无 sleep、无日志写盘、无隐式环境读取。

ObserveRequest 必有 context、keys、profile_id、scan_attempt_limit、allow_coordinate_fallback。检查一次必须传 limit=1；函数内部不能用 key 配置悄悄覆盖。轮播扫描由外层 workflow 持有计划，每次调用是一个新的 capture。

## 5. 动作合同：防止重复点击和过期坐标

ActionIntent 字段：action_id、kind（TAP/SWIPE/BACK/HOME/WAKE/DISMISS_KEYGUARD/START/STOP）、target_key?、expected_package、required_window_kind、source_observation、epoch、geometry、deadline_ns、idempotency_class、allow_coord、reason、preconditions。

1. coordinator durable 记录 intent，executor 验证其源 observation 未过期、epoch 一致、目标规则允许。
2. 操作前读取真实 focus。焦点采样到发出动作的间隔目标 ≤250ms；不能用几秒前截图附带的焦点代替。
3. 动态轮播目标max_action_age=1000ms、普通目标=2500ms是待T18a验证的初值，不是已证可行参数。年龄从实际定位依据样本采集结束算起，不能从OCR结束/cache返回算起。保留的Tesseract路径可能单次已超过此值，因此必须实现下面的快速重验证并测试可完成率，不能仅靠重复截屏陷入饥饿。
4. 慢识别后可采一张新图，在geometry/epoch/focus一致且目标位置与其安全ROI逐像素无损内容一致时，生成新的REVALIDATED观察，把原识别与新ROI相等证明一起引用；新动作依据的是新采样内容，不是给旧结果改时间戳。目标/布局移动或ROI改变时重新定位。每个动作最多2次新鲜度重验证并受原步骤deadline；仍失败则STALE_OBSERVATION退出，不无限循环。放宽像素相等为相似度需独立标定/质量门禁，不能用未验证pHash当语义保证。T18a必须证明legacy recipe和最终主OCR在此策略下都可完成；数值调整须给出采样到动作年龄与轮播变化实测。
5. 每个真正的动作提交前 epoch++，包括 BACK/HOME/滑动/启动/关闭/唤醒；所有旧动作令牌立即失效。
6. 发出一次底层调用，记录 ACKNOWLEDGED/REJECTED/UNKNOWN_EXECUTION。传输层没有“点击失败就自动补点”。
7. 通信中断无法判断是否执行时，先只读观察并核实状态。LIGHT/领取相关意图如果无法核实，结束本轮，禁止再次点击同一意图；恢复逻辑不能把 UNKNOWN 当普通 NO_MATCH。
8. 入口重试必须有“仍在首页”这一业务证据，且沿用次数上限；bag 重进必须有“目标页证明失败且允许重进”的上下文。不是网络重试。
9. exchange 无执行能力：profile 中无可点击 COORD_exchange，ActionPolicy 构造时拒绝 exchange TAP；不是仅靠 workflow 一处 if。
10. 只有奖励浮层证明分支允许 take；其它页面的“开心收下”不得借用此策略。dialog ALIAS 为空继续停用。

基线动作通过adbutils socket shell/input等显式单次请求，不经u2自动重放包装；Maa候选在同DevicePort内比较Maatouch/Minitouch等通道。三类fallback分开：初始化前可选择经验证的可用后端并记录原因；同一不可变图像可按固定route切OCR；动作一旦dispatch，transport冻结，REJECTED需证明未发送才可按策略重新观察，UNKNOWN绝不能切另一个transport或换ActionId再发。连接/服务重建使epoch失效并先检查跨运行未决效果。任何后端必须过丢响应不重复动作门禁，不能直接打开框架默认动作重试。

## 6. 状态图与上下文

```text
PRECHECK -> WAKE -> LAUNCH_HOME -> ENTER_SUBSIDY -> FIND_BAG
  -> PROVE_ACTIVITY -> CHECK_TERMINAL
  -> [DONE | EXCHANGE | PENDING]
  -> READ_BEFORE -> TAP_LIGHT -> OBSERVE_AFTER
      -> BROWSE(若识别到浏览横幅) -> BACK -> RECONCILE_LANDING
      -> VERIFY_PROGRESS / REWARD / PENDING / DONE
  -> FINAL_SCROLL(仅现有正常成功路径) -> COMMIT -> CLOSE_OR_STAY -> NOTIFY -> END
```

- ALREADY_MARKED 在设备 worker、OCR worker 启动前结束；命令/配置检查与旧接口的差异见变更表。
- FIND_BAG 不等价于 ACTIVITY；点击后必须证明当前页。HOME 不再进入 bag 全量识别。
- 浏览计时用 monotonic；BROWSE_SECONDS=15、BROWSE_DUR=800ms、BROWSE_MAX_SWIPES=60 保留，不能为了提速把实际任务缩成 2 秒测试值。
- BACK 后可能在活动页，也可能在频道页。先读进度；读不到才按策略检查 bag；只能按证据恢复。
- 最终 SWIPE_COUNT=20、SWIPE_DUR=300ms、SWIPE_WAIT=1s 首轮保留。优化等待不包含删除这些用户指定动作。
- lit=2/4 一旦确认为终态，后续不发 BACK/HOME/STOP，也不进入最终滑动；仍允许本地状态提交和单次通知。
- 普通失败的 HOME 收尾沿用旧有语义，精确序列来自 T01 oracle。若设备不可用或结果未知不能保证发出，报告 cleanup_status，禁止用“收尾完成”虚报。
- SIGNAL/设备通信故障后不会自动重新运行整条链；只读核实可以重试，次数与总时限均受上层约束。

## 7. 缓存与懒执行

缓存键：`pixel_sha256 + image_transform + recipe_hash + engine_version + model_hash + language + psm + output_box_mode`。识别文本和几何是纯内容缓存；动作许可不是缓存内容。

- 缓存属于本次运行，默认 LRU 图像内存预算 64MiB；超出淘汰解码图，不删工件。结果缓存默认 128 项。
- 新 capture 即使像素 hash 相同，可以复用纯 OCR 结果，但必须重建带新 capture_id/epoch 的候选与动作令牌；焦点/状态证明不能跨帧复用。
- 点击、滑动、BACK、焦点变化、旋转都失效当前 observation。OCR hash 命中不能让旧操作计划复活。
- 一次 capture 中 full-page OCR 可同时服务 done/exchange/pend/count；原 recipe 次序和 token 内容不因 key 变化重复计算。
- `legacy-parity` 按原优先级懒计算；`single-device-v2` 按 target route 显式配置引擎/ROI 次序，不动态用“最高分引擎”拍脑袋切换。
- 区域与胶囊预处理一次，多个 PSM 读同一裁片。首个合法命中即可停止后续识别，但必须保留该通道此前用于稳定排序的完整候选集。
- 不将旧版“全页找不到文字”当作裁图也不可能误报的保证；所有负例用完整生产级联实际跑。

## 8. 截止时间与性能预算

Deadline 保存绝对 monotonic_ns；`child(limit) = min(parent_deadline, now+limit)`；子函数不能重置父截止时间。

| 阶段 | 初始上限/预算 | 超时处理 |
|---|---|---|
| 单次焦点读取 | 2s | 有界重读；非 APP 不执行 |
| 单次 PNG | 5s | INVALID/TIMEOUT；不复用上一帧 |
| 单次 XML（含 U2 内部重试） | 5s | 放弃本次 XML，按页面路由视觉；worker 卡死由 supervisor 回收 |
| 单次轻量 OCR | 5s hard limit，热路径 p95 目标1.5s | TIMEOUT，可按剩余预算跑已有 fallback；不自动变成功 |
| 单次 Tesseract recipe | 8s | 杀进程组，留 stderr，不能累计无上限 |
| 普通页面等待 | 8s | 从 0.3/0.5/1s 等阶梯观察，未到状态按阶段失败 |
| bag 轮播搜索 | 45s，总上限12次观察 | 单次 presence=1；scan 才拥有12次预算；现有 interval3s 先保留 |
| 一次 bag 进入与证明 | 90s，点击尝试最多3次 | 剩余预算不足不再开始新一轮 |
| 入口恢复 | 最多2次 BACK+补点，共3次入口点击 | 沿用 rc4，不掉进 bag 扫描 |
| 完整业务 | 600s 初值 | 终止，记录 timeout_phase；不自动重复签到 |
| 通知 | 15s，1次 | 单独失败，不改业务 rc |
| 收尾/写摘要 | 10s 协作退出余量 | 已有证据仍可读；不能假装原子提交成功 |

初值在 T03/T16 实测后单独版本化，不是已测可用的保证。若正常页面必须超过预算，先给出 measured breakdown，不能隐式叠重试。systemd 外部 TimeoutStartSec 应覆盖 600s+通知+收尾和小幅余量，候选暂定12min，最终由测量确定；现役25min在切换前不修改。

## 9. 配置与版本

- 新配置为 config.toml，带 config_schema_version；profile 路径/版本固定，业务别名/ROI/recipe 移至公共 profiles，不含运行时状态。
- 优先级：内建默认 < 选择的配置文件 < 白名单环境变量 < CLI；有效值附来源。标定 profile 只能通过显式 profile 切换/受校验字段修改，不用任意环境变量污染。
- 旧 pdd-ocr.conf 用专门 parser：不 source、不 eval，仅与旧代码相同的键名单；输出规范化配置，不重写主机原文件。VLM_* 仍仅离线工具使用。
- 旧脚本和新程序各自有配置路径。未切换前不把新键写入旧共享 conf，防止老程序 rc78。
- 模型 manifest 固定 det/rec/cls/字典哈希、许可证、预处理和引擎版本，模型路径只读。runtime 禁止自动下载模型，缺模型在设备动作前报 preflight 错误。
- RapidOCR/ORT候选线程1/2/4、inter_op=1；Maa用实际受锁版本支持的执行器/参数，若线程固定则如实记录或采用受审适配补丁，不写并不存在的配置开关。关闭方向分类只在固定方向语料质量门禁通过后启用。不能用mutable默认config代替本项目recipe。

## 10. 状态、通知与工件事务

运行锁：Linux flock，按真实device_id的稳定绝对路径唯一。薄LeaseGuard监督进程持锁，Coordinator不是唯一持锁者；DeviceWorker继承同一open-file-description的lease fd，避免Coordinator被SIGKILL时先释放锁。LeaseGuard监督整组进程、IPC断开时禁止新动作并回收worker/native子进程，子进程组/cgroup消亡确认后才释放。systemd运行使用KillMode=control-group；手动入口同样经LeaseGuard，不能exec绕掉监督。LeaseGuard是运行期轻量launcher层，不增加第二个业务执行器；CPU/RSS测量计入它。若连监督层也异常消失，新启动必须检查owner/cgroup与durable未决意图，先进入quarantine/只读核实，不能凭flock空闲直接重新签到。远端已发送动作仍可能执行，journal中的UNKNOWN不因本地进程退出而清零。手动point/run/probe/find/shot也拿同一锁；不得用不同cwd生成不同锁。

状态存储：原子写同目录 temp→flush/fsync→os.replace→目录 fsync。先 durable 业务结果/动作 journal，再更新账本和日标记；每步记录 commit receipt。失败不回滚已执行的手机动作，不删除已确认的完成记录。

恢复：未决LIGHT/TAKE按device_id+账号槽位+目标活动/周期（未知周期用保守活动槽位）索引，不只按run_id/business_date/ActionId。启动及每个领取前调用load_unresolved，跨午夜、force、新release和回滚都不能靠换ActionId绕过。发现未核实意图只读核实；无足够证据则保持UNKNOWN并阻断相同逻辑效果，下一天也一样，直到可证明其结果/活动周期已更换或用户显式解除该具名未决记录。不能自动按日期清除UNKNOWN。已有日标记时不重跑。通知有PREPARED/ATTEMPTED/ACK/UNKNOWN状态，重启不自动再发未知通知。

本地 JSONL 不是远端事务日志；不能宣称 exactly-once。合同提供本机互斥、单次发送、未知状态可见与有条件核实。

工件目录：`runs/<business-date>/<run-id>/`，含 manifest、events.jsonl、summary.json、兼容 summary.txt、frames/<capture-id>/、ocr/<reading-id>/、decisions/、report.html。共享根部的 `.done-日期` 与旧账本通过兼容存储器保留。7天保留窗口不删除固定测试语料，不删除未解决动作 journal；有容量上限和显式清理策略。

RunEvent 必有 schema_version、seq、run/capture/reading/decision/action 引用、phase、event_name、wall/monotonic 时间、duration、status、release/config/model hash、redacted_details。日志不能仅写“没找到”：至少区分字未匹配、区域拒绝、焦点拒绝、过期、解码失败、执行超时。

原始 HTTP 错误/URL 先脱敏，端点值与 key 不进入 events、异常 repr、报告、fixture；正文按上限截取并记录 truncated。识别原文来自手机，保存在本地私有工件，公开语料另做脱敏验证。

## 11. 回放与 CLI

保留 run/run force/probe/find/point/shot/status/replay；point 收像素。新包装脚本只是 exec 入口，不包含业务判断。未知命令原行为“usage、rc0”在兼容入口保留，新显式严格 CLI 可用 argparse rc2，并登记接口差异。

新增命令（规划）：

```text
pddcheck check-config --offline
pddcheck doctor --offline
pddcheck replay RUN_DIR --mode exact
pddcheck replay RUN_DIR --mode reprocess --profile PROFILE
pddcheck replay RUN_DIR --mode trace
pddcheck bench DATASET --profile PROFILE --output DIR
pddcheck report RUN_DIR
```

- exact：只读当时记录的 OCR/XML/配置/判定，不重新识别；旧证据没有 OCR 时返回 INCOMPLETE，不伪造精确回放。
- reprocess：当前引擎重识别固定 PNG，明确与原始结果对照；离线无设备、无端点读取、无通知。
- trace：用时间有序的 capture 与 fake action receipt 驱动同一纯状态机；缺关键帧时标覆盖不足。
- 旧 replay --ocr 映射 reprocess；--label/--scan/--size/--all 保留兼容解释；新 CLI 支持显式 --key 选帧目标，不再要求复制改文件名。
- report 可以离线重复生成。HTML escape 所有屏幕文本/日志，不执行 OCR 内容或远端脚本。
- doctor 默认离线；只有显式 live 模式才创建设备端服务，报告将做哪些设备维护动作。status 保留设备在线信息模式，另外提供 --offline 纯本地模式。

T02 必须把所有端口序列化往返、错误映射和 fake 行为建为公共契约测试；之后模块作者只补实现，不再重新解释这些条款。
