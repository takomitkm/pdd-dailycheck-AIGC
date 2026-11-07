"""profile 数据模型与严格装载（契约 §9；T05）。

原则：
- 内建默认 = DEFAULTS（本模块唯一事实源）；profiles/pdd/v1/profile.toml 是同一组值的
  序列化快照，测试保证两者永不漂移。
- 装载规则：内建默认 < 所选 profile 文件；**未知节/未知键/坏值一律 ConfigError**
  （D06：配置坏在设备动作之前就停，绝不带着半套配置开跑——旧脚本 78 语义的对应物）。
- 数值范围与旧 ocr_conf_check 逐条对齐；region/pill/coord 是 0..1 屏幕比例。
"""

from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pddcheck.config.errors import ConfigError

_PSM_RANGE = (0, 32)


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    serial: str
    pkg: str
    home_activity: str


@dataclass(frozen=True, slots=True)
class TargetSpec:
    alias: tuple[str, ...] = ()
    overlap: int = 3
    region: tuple[float, float, float, float] | None = None
    pill: tuple[float, float, float, float] | None = None
    # 第二胶囊框（ADR-003）：同一目标在不同页型上位置不同时用；缺省 None=不启用，
    # 因此现有 profile 与标定值完全不变（向后兼容）。
    pill_channel: tuple[float, float, float, float] | None = None
    pill_mode: str = "inv"          # inv（反色+硬阈值）| color（原色），对齐旧 PILL_MODE_*
    coord: tuple[float, float] | None = None
    find_retry: int | None = None   # None = 用全局 find_retry
    find_interval: int | None = None


@dataclass(frozen=True, slots=True)
class OcrConfig:
    lang: str
    psm: int
    psm_page: int
    min_conf: int
    psm_band: tuple[int, ...]
    psm_band_by_key: tuple[tuple[str, tuple[int, ...]], ...]
    band_scale: int
    band_cutoff: int
    pill_th: int
    pill_scales: tuple[int, ...]
    pend_psm: tuple[int, ...]
    pend_line_re: str
    pend_days_re: str
    count_text: str


@dataclass(frozen=True, slots=True)
class FlowConfig:
    scroll_top: int
    top_retry_key: str
    top_swipes: int
    entry_retry: int
    entry_retry_wait: int
    focus_retry: int
    focus_retry_wait: int
    restart_app: bool
    launch_wait: int
    step_wait: int
    find_retry: int
    find_interval: int
    popup_max: int
    popup_wait: int
    swipe_x: float
    swipe_y1: float
    swipe_y2: float
    swipe_dur: int
    swipe_count: int
    swipe_wait: int
    top_swipe_y1: float
    top_swipe_y2: float
    browse_seconds: int
    browse_dur: int
    browse_wait: int
    browse_max_swipes: int
    browse_prove: bool
    browse_back: bool
    keep_days: int
    close_app_on_ok: bool
    no_close_lit: tuple[int, ...]
    abort_if_locked: bool
    check_done_before: str
    prove_key: str
    prove_max: int
    recovery_no_coord: bool
    min_overlap: int


@dataclass(frozen=True, slots=True)
class Profile:
    device: DeviceConfig
    flow: FlowConfig
    ocr: OcrConfig
    targets: tuple[tuple[str, TargetSpec], ...]

    def target(self, key: str) -> TargetSpec:
        for name, spec in self.targets:
            if name == key:
                return spec
        raise KeyError(key)

    @property
    def target_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.targets)


def _ratio4(v: object, where: str) -> tuple[float, float, float, float]:
    if not isinstance(v, list) or len(v) != 4 or any(type(x) not in (int, float) for x in v):
        raise ConfigError(f"{where} 必须是 [x1,y1,x2,y2] 四个 0..1 的数")
    x1, y1, x2, y2 = (float(x) for x in v)  # type: ignore[arg-type]
    for val in (x1, y1, x2, y2):
        if not 0.0 <= val <= 1.0:
            raise ConfigError(f"{where} 的坐标必须在 0..1（屏幕比例）：{v}")
    if x2 <= x1 or y2 <= y1:
        raise ConfigError(f"{where} 必须是 x2>x1、y2>y1：{v}")
    return (x1, y1, x2, y2)


def _ratio2(v: object, where: str) -> tuple[float, float]:
    if not isinstance(v, list) or len(v) != 2 or any(type(x) not in (int, float) for x in v):
        raise ConfigError(f"{where} 必须是 [fx,fy] 两个 0..1 的数")
    fx, fy = (float(x) for x in v)  # type: ignore[arg-type]
    if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
        raise ConfigError(f"{where} 的坐标必须在 0..1：{v}")
    return (fx, fy)


def _int_in(v: object, lo: int, hi: int, where: str) -> int:
    if type(v) is not int or not lo <= v <= hi:
        raise ConfigError(f"{where} 要 {lo}..{hi} 的整数，得到 {v!r}")
    return v  # type: ignore[return-value]


def _int_list(v: object, where: str, *, lo: int | None = None, hi: int | None = None) -> tuple[int, ...]:
    if not isinstance(v, (list, tuple)) or not v or any(type(x) is not int for x in v):
        raise ConfigError(f"{where} 要非空的整数表（空格分开的 psm 表的对应物）：{v!r}")
    if lo is not None:
        for x in v:  # type: ignore[union-attr]
            if not lo <= x <= (hi if hi is not None else lo):  # type: ignore[operator]
                raise ConfigError(f"{where} 里有元素不在 {lo}..{hi}：{v!r}")
    return tuple(v)  # type: ignore[arg-type]


def _check_target(key: str, spec: TargetSpec) -> None:
    if not (1 <= spec.overlap <= 20):
        raise ConfigError(f"targets.{key}.overlap 要 1..20 的整数：{spec.overlap}")
    if spec.pill_mode not in ("inv", "color"):
        raise ConfigError(f"targets.{key}.pill_mode 只认 inv|color：{spec.pill_mode!r}")
    if spec.pill is None and spec.pill_mode != "inv":
        raise ConfigError(f"targets.{key}.pill_mode=color 但没有 pill 框")
    if spec.find_retry is not None and spec.find_retry < 1:
        raise ConfigError(f"targets.{key}.find_retry 必须 >=1：{spec.find_retry}")
    if spec.find_interval is not None and spec.find_interval < 0:
        raise ConfigError(f"targets.{key}.find_interval 必须 >=0")


def _check_ocr(ocr: OcrConfig) -> None:
    _int_in(ocr.psm, *_PSM_RANGE, "ocr.psm")
    _int_in(ocr.psm_page, *_PSM_RANGE, "ocr.psm_page")
    _int_in(ocr.min_conf, 0, 100, "ocr.min_conf")
    _int_list(ocr.psm_band, "ocr.psm_band")
    _int_in(ocr.band_scale, 1, 8, "ocr.band_scale（裁片坐标回算的除数，0 会除零）")
    _int_in(ocr.band_cutoff, 0, 49, "ocr.band_cutoff")
    _int_in(ocr.pill_th, 0, 255, "ocr.pill_th")
    _int_list(ocr.pill_scales, "ocr.pill_scales", lo=1, hi=8)
    _int_list(ocr.pend_psm, "ocr.pend_psm")
    if not ocr.lang:
        raise ConfigError("ocr.lang 不能为空")
    for key, band in ocr.psm_band_by_key:
        _int_list(band, f"ocr.psm_band_by_key.{key}")
    if not ocr.count_text:
        raise ConfigError("ocr.count_text 不能为空")


def _build_profile(doc: dict) -> Profile:
    if doc.get("meta", {}).get("schema_version") != 1:
        raise ConfigError("meta.schema_version 必须是 1")

    def section(name: str) -> dict:
        sec = doc.get(name, {})
        if not isinstance(sec, dict):
            raise ConfigError(f"[{name}] 必须是表")
        return sec

    dev = section("device")
    device = DeviceConfig(
        serial=str(dev.get("serial", "")),
        pkg=str(dev.get("pkg", "")),
        home_activity=str(dev.get("home_activity", "")),
    )
    if not device.serial or not device.pkg or not device.home_activity:
        raise ConfigError("[device] 的 serial/pkg/home_activity 都不能为空")

    known_flow = {f.name for f in dataclasses.fields(FlowConfig)}
    flow_doc = section("flow")
    unknown = sorted(set(flow_doc) - known_flow)
    if unknown:
        raise ConfigError(f"[flow] 有未知键：{unknown}（名单外一律拒绝，D06）")
    flow_doc = {**dataclasses.asdict(DEFAULTS.flow), **flow_doc}
    flow_doc["no_close_lit"] = tuple(flow_doc["no_close_lit"])
    flow = FlowConfig(**flow_doc)

    known_ocr = {f.name for f in dataclasses.fields(OcrConfig)}
    ocr_doc = section("ocr")
    unknown = sorted(set(ocr_doc) - known_ocr)
    if unknown:
        raise ConfigError(f"[ocr] 有未知键：{unknown}（D06）")
    base = {f.name: getattr(DEFAULTS.ocr, f.name) for f in dataclasses.fields(OcrConfig)}
    base.pop("psm_band_by_key")
    ocr_doc = {**base, **ocr_doc}
    by_key = ocr_doc.pop("psm_band_by_key", {})
    if not isinstance(by_key, dict):
        raise ConfigError("[ocr.psm_band_by_key] 必须是表")
    # TOML 里的表值是 list；合同要求不可变（tuple），逐个转换
    for list_field in ("psm_band", "pill_scales", "pend_psm"):
        ocr_doc[list_field] = _int_list(ocr_doc[list_field], f"ocr.{list_field}",
                                        lo=1 if list_field == "pill_scales" else None,
                                        hi=8 if list_field == "pill_scales" else None)
    ocr = OcrConfig(
        **ocr_doc,
        psm_band_by_key=tuple(sorted((str(k), tuple(v)) for k, v in by_key.items())),
    )

    targets_doc = section("targets")
    known_targets = {name for name, _ in DEFAULTS.targets}
    unknown = sorted(set(targets_doc) - known_targets)
    if unknown:
        raise ConfigError(f"[targets] 有未知目标：{unknown}（标定数据的增删要走变更记录）")
    targets: list[tuple[str, TargetSpec]] = []
    for name, _ in DEFAULTS.targets:
        tdoc = targets_doc.get(name, {})
        if not isinstance(tdoc, dict):
            raise ConfigError(f"[targets.{name}] 必须是表")
        known_t = {f.name for f in dataclasses.fields(TargetSpec)}
        t_unknown = sorted(set(tdoc) - known_t)
        if t_unknown:
            raise ConfigError(f"[targets.{name}] 有未知键：{t_unknown}")
        merged = {**dataclasses.asdict(DEFAULTS.target(name)), **tdoc}
        if merged["alias"] is not None and not isinstance(merged["alias"], list):
            raise ConfigError(f"targets.{name}.alias 必须是字符串数组")
        if "pill_channel" in tdoc and merged["pill_channel"] is not None:
            _ratio4(merged["pill_channel"], f"targets.{name}.pill_channel")
        spec = TargetSpec(
            alias=tuple(str(a) for a in (merged["alias"] or [])),
            overlap=int(merged["overlap"]),
            region=None if merged["region"] is None else _ratio4(merged["region"], f"targets.{name}.region"),
            pill=None if merged["pill"] is None else _ratio4(merged["pill"], f"targets.{name}.pill"),
            pill_channel=None if merged.get("pill_channel") is None
            else _ratio4(merged["pill_channel"], f"targets.{name}.pill_channel"),
            pill_mode=str(merged["pill_mode"]),
            coord=None if merged["coord"] is None else _ratio2(merged["coord"], f"targets.{name}.coord"),
            find_retry=None if merged["find_retry"] is None else _int_in(merged["find_retry"], 1, 99, f"targets.{name}.find_retry"),
            find_interval=None if merged["find_interval"] is None else _int_in(merged["find_interval"], 0, 99, f"targets.{name}.find_interval"),
        )
        _check_target(name, spec)
        targets.append((name, spec))

    profile = Profile(device=device, flow=flow, ocr=ocr, targets=tuple(targets))
    _check_ocr(profile.ocr)
    names = profile.target_names
    for field in (flow.top_retry_key, flow.check_done_before, flow.prove_key):
        if field not in names:
            raise ConfigError(f"flow 引用了不存在的 target：{field!r}（现有：{names}）")
    return profile


# ---------------------------------------------------------------- 内建默认（唯一事实源）

DEFAULTS = Profile(
    device=DeviceConfig(
        serial="192.168.1.110:16132",
        pkg="com.xunmeng.pinduoduo",
        home_activity="com.xunmeng.pinduoduo.ui.activity.MainFrameActivity",
    ),
    flow=FlowConfig(
        scroll_top=2, top_retry_key="subsidy", top_swipes=4,
        entry_retry=2, entry_retry_wait=3, focus_retry=3, focus_retry_wait=1,
        restart_app=True, launch_wait=8, step_wait=4,
        find_retry=3, find_interval=2, popup_max=3, popup_wait=2,
        swipe_x=0.75, swipe_y1=0.9375, swipe_y2=0.546875,
        swipe_dur=300, swipe_count=20, swipe_wait=1,
        top_swipe_y1=0.328125, top_swipe_y2=0.8984375,
        browse_seconds=15, browse_dur=800, browse_wait=0, browse_max_swipes=60,
        browse_prove=True, browse_back=False, keep_days=7, close_app_on_ok=True,
        no_close_lit=(2, 4), abort_if_locked=True, check_done_before="light",
        prove_key="bag", prove_max=3, recovery_no_coord=True, min_overlap=3,
    ),
    ocr=OcrConfig(
        lang="chi_sim+eng", psm=11, psm_page=6, min_conf=40,
        psm_band=(7,), psm_band_by_key=(("browse", (7, 6)), ("done", (7, 6))),
        band_scale=3, band_cutoff=1, pill_th=120, pill_scales=(1, 2),
        pend_psm=(6, 11, 12),
        pend_line_re="任务已完成|待兑换|天后可",
        pend_days_re="[0-9]{1,2}天后",
        count_text="再点亮|天内点亮",
    ),
    targets=(
        ("popup", TargetSpec(alias=("关闭", "跳过广告", "暂不", "以后再说"), overlap=2,
                             region=(0.45, 0.0, 1.0, 0.45))),
        ("dialog", TargetSpec(alias=(), overlap=4, region=(0.05, 0.10, 0.95, 0.90),
                              coord=(0.85694, 0.17344))),
        ("subsidy", TargetSpec(alias=("百亿补贴", "官方补贴"), overlap=4,
                               region=(0.0, 0.30, 0.40, 0.80), coord=(0.125, 0.46875))),
        ("bag", TargetSpec(alias=("抽福袋", "去抢购"), overlap=3,
                           region=(0.0, 0.35, 1.0, 0.85), coord=(0.13889, 0.69922),
                           pill=(0.02, 0.64, 0.32, 0.78), pill_mode="color",
                           find_retry=12, find_interval=3)),
        ("light", TargetSpec(alias=("立即点亮",), overlap=3,
                             region=(0.0, 0.08, 1.0, 0.42), coord=(0.83056, 0.22266),
                             pill=(0.597, 0.184, 1.0, 0.270), pill_mode="inv")),
        ("done", TargetSpec(alias=("已点亮", "明日再来", "明天再来", "已使用"), overlap=3,
                            region=(0.0, 0.08, 1.0, 0.42),
                            pill=(0.597, 0.184, 1.0, 0.270), pill_mode="inv")),
        ("exchange", TargetSpec(alias=("立即兑换", "去兑换"), overlap=3,
                                region=(0.0, 0.08, 1.0, 0.42),
                                pill=(0.597, 0.184, 1.0, 0.270), pill_mode="inv")),
        ("browse", TargetSpec(alias=("浏览当前页面", "即可点亮"), overlap=4,
                              region=(0.0, 0.30, 1.0, 0.45))),
        ("prize", TargetSpec(alias=("翻倍券", "提前锁定"), overlap=3,
                             region=(0.0, 0.30, 1.0, 0.65))),
        ("take", TargetSpec(alias=("开心收下",), overlap=3,
                            region=(0.0, 0.50, 1.0, 0.70), coord=(0.49861, 0.58750),
                            pill=(0.15, 0.553, 0.849, 0.622), pill_mode="inv")),
        ("pend", TargetSpec(alias=("任务已完成", "天后可兑换", "待兑换"), overlap=3,
                            region=(0.0, 0.08, 1.0, 0.45))),
    ),
)

_LAST_SEEN_TARGETS = DEFAULTS.target_names  # 兼容旧引用；交叉校验在 load_profile 内做


def defaults() -> Profile:
    """内建默认（唯一事实源的只读入口）。"""
    return DEFAULTS


def load_profile(path: Path | None = None) -> Profile:
    """无 path → 内建默认；有 path → 严格 TOML 覆盖（未知节/键/坏值 = ConfigError）。"""
    if path is None:
        return DEFAULTS
    doc = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return _build_profile(doc)
