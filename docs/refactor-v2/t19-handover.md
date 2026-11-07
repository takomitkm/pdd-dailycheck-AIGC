# T19 交接：pddcheck（PDD 每日签到 Python 重构版）

> 状态：**代码完备，生产切换待用户批准两件事**（见「待用户决定」）。
> 分支 `refactor-v2`；测试 377 passed + 4 skipped（2026-11-07）。

## 一句话架构

单设备 actor：`cli/app.py`（离线命令 + run）→ `cli/bootstrap.py`（组装，run_stages 开关）
→ `workflow/flow.py` run_once（日标记→锁→观察→决策→执行→核实→标记/账本/通知）
→ `perception`（页型判定 pagekind、定位 locate_all、多通道观察 observe）
→ `vision`（Tesseract 3 态 TSV、band/pill 裁片+几何、EngineLease）
→ `device`（AdbDevice：显式 HOME_ACT、前台护栏、`/sdcard` dump 回退）
→ `storage`（.done-<date> 日标记、单数字账本、flock RunLease、Journal intent/receipt）
→ `notify`（5 分支正文、单次重发、D07 严格 JSON 校验）→ `evidence`/`replay`（内容寻址工件、JSONL 事件、回放）。

标定与真机发现全部在 `docs/refactor-v2/t18a-calibration-findings.md`；
ADR：001（后端）、002（RapidOCR 不换）、003（第二胶囊框）。

## 部署（h61 = Debian 13 / Python 3.13.5）

```
/home/user/pddcheck-staging/          # 发布根
  releases/<ver>/site/                # stdlib wheel 展开目录
  current                             # 当前版本号（原子指针）
  release.py                          # expand/switch/rollback
```

- 构建发布：Windows 侧 `scripts/release.py build --version X` → scp → `expand`。
- 运行：`PYTHONPATH=$PWD/releases/<ver>/site python3 -m pddcheck.cli.app <cmd>`。
- 0.1.24 已部署并真机验证（`version`/`doctor`/`run --stages` 全通）。

## 日常运行

```
pddcheck run --device <serial>            # 只做点亮段（旧流程日标记在则安全跳过）
pddcheck run --device <serial> --stages   # 先走 就绪→入口→福袋（完整链路）
```

- 环境变量：`PDDCHECK_EVIDENCE`（证据根）、`PDDCHECK_STATE`（锁/日志）、`PDDCHECK_NO_PUSH=1`（不推送）。
- 退出码见 `src/pddcheck/exits.py`：0 OK、1 未验证→映射 6、2 设备掉线、3 锁忙、
  4 入口失败、5 福袋失败、6 未点亮、7 焦点错误、69 无 adb、73 状态目录、75 锁忙、78 预检失败。
- lit 语义：1=今日已点亮（点前判定）、2=可兑换、3=三步点完+弱证明（弱=legacy_text_without_counter）、
  4=pend（进程码 0）。

## 真机标定速查（真机实测，2026-11-07）

| 目标 | 通道 | 标定 | 点击点 |
|---|---|---|---|
| 入口「百亿补贴」（艺术字） | coord | (0.125, 0.46875) | (90,600) |
| 频道页「抽福袋」 | pill color×2 psm7 | [0.472,0.375,0.75,0.4375]（**ADR-003 待批准**） | (435,524) |
| 活动页「今日已点亮」 | pill inv×2 psm7 | [0.597,0.184,1.0,0.270]（现有 profile 值即可） | (600,290) |

页面判据（pagekind）：首页=推荐/食品/女装/限时秒杀；频道页=百亿补贴品质保障/抢低至5折；
活动页=天内再点亮/共100元券/今日已点亮。活动页与频道页同为 `NewPageActivity`，**必须靠文本**。

## 测试与验证

- 全量：`PYTHONPATH=src python -m pytest tests -p no:cacheprovider`
- 行为基线 47 案 ×2 + 负例 11 + 变异 11/11 killed + 审计 8 claims：见 `docs/refactor-v2/`、`reports/`。
- 真机演练：`scripts/rehearse_real.py`（分级放行动作，JSONL 取证）。

## 生产 timer（2026-11-07，用户批准接管）

```
pdd.timer      disabled   ← 旧流程已停（文件仍在，可回滚）
pddcheck.timer 10:00:00  enabled   ← pddcheck 接管生产
```

- h61 版本 `0.1.26`（`/home/user/pddcheck-staging/current`）
- env `~/.config/pddcheck/env`（600）：`PDDCHECK_DEVICE=192.168.1.110:16132`，
  `PDDCHECK_EVIDENCE=~/Desktop/pdd-runs`，`PDDCHECK_STATE=~/.local/share/pddcheck-state`，
  **无 NO_PUSH**（允许推送，端点 `~/Desktop/pdd-push.url` present）
- service：`run --device ${PDDCHECK_DEVICE} --stages`，`Restart=no`
- 批准标定已落地：`profiles/pdd/v1/profile.toml` + `DEFAULTS.target("bag").pill_channel = (0.472,0.375,0.75,0.4375)`（CLI 优先读 profile，fallback 同值）

**回滚到旧流程（一行）**
```
ssh deb-h61 'systemctl --user disable --now pddcheck.timer; systemctl --user enable --now pdd.timer'
```

## 待办（仅一项，等自然条件）

- **未签到日真实 lit3 真点亮**：今日已签到，不能伪造未签到状态。将在下一次自然无 `.done`
  标记的运行中由 pddcheck 生产 timer 验证；如需手动窗口，请指定（并确认当日确实未签到）。


## 已知边界

- XML 通道在频道页基本无效（WebView 渲染），依赖 OCR；`uiautomator dump /dev/tty` 返回空 → 用 /sdcard 回退。
- 「今日已点亮」整页 OCR 读不到（在进度条右侧），必须走裁片通道。
- 阶段失败（rc4/5/7）不写标记、只 HOME 收尾；绝不拿错页事实做弱证明。
- 业务动作一律过前台护栏（expected_package + window APP）；坐标兜底只认标定值。
- 旧 `pdd.sh` 冻结未动（sha256 8bd6e038…），切流前仍是生产兜底。
