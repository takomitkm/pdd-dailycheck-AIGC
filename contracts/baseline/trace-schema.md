# oracle trace 字段规格（trace-schema）

用途：T15 集成断言用的「效果轨迹」字段定义。现役桩沙箱只断言**计数**（taps/backs/pushes），
trace 把同一份事件流升级为**有序序列**断言。来源：`SBX_EVENTS`（每行一个桩事件）、
`SBX_PUSH`（TITLE/正文）、stdout 的 `lit=` 行、文件系统写入（marker/ledger/pause）。

## 字段

```jsonc
{
  "case": "happy-ocr",              // 用例名（=behavior-v1.json id+name）
  "resolution": "720x1280",
  "seq": [                           // 有序桩事件，按发生顺序
    {"op": "connect",   "detail": "192.168.1.110:16132", "assert": true},
    {"op": "key",       "key": "KEYCODE_WAKEUP",          "assert": true},
    {"op": "key",       "key": "KEYCODE_BACK",            "assert": true},
    {"op": "tap",       "x": 100, "y": 600, "assert": true},
    {"op": "swipe",     "x1": 540, "y1": 1200, "x2": 540, "y2": 700,
     "dur_ms": 300, "assert": ">=1"},   // browse 类只能下界断言
    {"op": "force_stop","pkg": "com.xunmeng.pinduoduo", "assert": true},
    {"op": "key",       "key": "KEYCODE_HOME",            "assert": true}
  ],
  "focus_precondition": [            // 每个业务 tap/swipe 前要求的前台断言（T15 新增）
    {"before_op_index": 3, "package": "com.xunmeng.pinduoduo", "window": "app"}
  ],
  "notify": [                        // 一次 attempt 一条；标题按 UTF-8 字节断言
    {"title_bytes": "50 44 44 20 e2 9c 85", "title_text": "PDD ✅", "attempt_count": 1}
  ],
  "writes": [                        // 文件副作用
    {"path": "runs/.done-<business_date>", "op": "create", "assert": true},
    {"path": "pause", "content": "0", "assert": true}
  ],
  "stdout": {"lit": 3, "rc": 0}
}
```

## 断言语义

- `assert: true` = 必须恰好出现一次且位置正确（相对相邻事件）；
- `assert: ">=1"` / `">=N"` = 下界（browse 类墙钟滑动）；
- 未列出的操作**不允许出现**（严格模式），除非该用例显式声明 `allow_extra`；
- `notify.title_bytes` 是精确字节（旧的 grep 子串断言升级为字节相等，见 behavior-v1
  gaps 第 3 条）；无端点/发送失败时 notify 数组必须为空。

## 两个示例

1. `happy-ocr`（lit=3 正常成功）：connect → wake → launch(无 BACK) → tap(subsidy ocr) →
   tap(bag ocr) → tap(light) → swipe≥1(browse) → count 读数 4→3 → force_stop → HOME；
   notify 1 条 `PDD ✅`；writes: marker create + pause=0。
2. `shade-slashless-focus`（rc=7 零枪）：connect → wake → launch BACK ×1 →
   focus 读到 StatusBar → **无任何 tap/swipe** → key HOME（失败收尾，close 判定=0）；
   notify 1 条 `PDD ❌ 退出码 7`；无 marker/pause 写入。
