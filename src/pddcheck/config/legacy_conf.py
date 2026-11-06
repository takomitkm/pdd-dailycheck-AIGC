"""旧 pdd-ocr.conf 的只读解析器（T05，B01/D06 的兼容半边）。

与 pdd.sh 的 load_ocr_conf（L316-357）+ ocr_conf_check（L370-395）逐条对齐：

- 行格式：去行首尾空白；# 注释跳过；空 `=x` 的键、非 KEY=VALUE、键名字符集不合法 → 带行号报错；
- 名单外键 → 报错（ALIAS_/REGION_/PILL_<标定框>/COORD_/DEVICE 这些写进来一个字都不生效，
  「以为改了其实没改」比不写更坏——旧 78 语义）；
- 离线工具键（VLM_BACKEND/VLM_API_URL_FILE/VLM_MODEL/VLM_TIMEOUT/VLM_PROMPT/
  VLM_PROMPT_FILE/VLM_MAX/VLM_LOCAL_MAX_PNG/PDD_SH）→ 认得但不应用（计数返回）；
- 凭据键（VLM_API_URL/VLM_API_KEY/VLM_STUB）→ 直接报错（不许写在这份文件里）；
- 值域闸门与 ocr_conf_check 一致：psm 0..32、minconf 0..100、BAND_SCALE 1..8、
  BAND_CUTOFF 0..49、PILL_TH 0..255、psm 表/缩放表非空整数、PILL_MODE_* 只认 inv|color；
- 环境变量压过文件那一层（OCR_CONF_ENVHOLD）不在此处——本解析器只吃文本，
  环境优先级由调用方决定；`~/` 与 `$HOME` 展开**不做**（新程序无 HOME 概念，
  路径键本就不在名单里）。
- B01：文件不存在/读不了时回退内建默认的决定在调用方（load_optional_legacy_conf），
  解析器对内容负责。
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from pddcheck.config.errors import LegacyConfError

_FOREIGN_KEYS = frozenset({
    "VLM_BACKEND", "VLM_API_URL_FILE", "VLM_MODEL", "VLM_TIMEOUT", "VLM_PROMPT",
    "VLM_PROMPT_FILE", "VLM_MAX", "VLM_LOCAL_MAX_PNG", "PDD_SH",
})
_CREDENTIAL_KEYS = frozenset({"VLM_API_URL", "VLM_API_KEY", "VLM_STUB"})
_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BAND_KEY_RE = re.compile(r"^OCR_PSM_BAND_(?P<key>[a-z]+)$")
_MODE_KEY_RE = re.compile(r"^PILL_MODE_(?P<key>[a-z]+)$")


@dataclasses.dataclass(frozen=True, slots=True)
class LegacyConf:
    values: tuple[tuple[str, str], ...]   # 白名单内的原始键值（字符串，未转型）
    applied: int
    foreign: int                          # VLM_ 那批：认得、归离线工具、这边不应用

    def get(self, key: str) -> str | None:
        for k, v in self.values:
            if k == key:
                return v
        return None

    def band_by_key(self) -> tuple[tuple[str, str], ...]:
        return tuple((m.group("key"), v) for k, v in self.values
                     if (m := _BAND_KEY_RE.match(k)))

    def modes_by_key(self) -> tuple[tuple[str, str], ...]:
        return tuple((m.group("key"), v) for k, v in self.values
                     if (m := _MODE_KEY_RE.match(k)))


def _fail(line_no: int, line: str, reason: str) -> LegacyConfError:
    return LegacyConfError(f"第 {line_no} 行「{line}」{reason}")


def _int_in(v: str, line_no: int, key: str, lo: int, hi: int) -> None:
    if not v or not re.fullmatch(r"[0-9]+", v) or not lo <= int(v) <= hi:
        raise _fail(line_no, f"{key}={v}", f"要 {lo}..{hi} 的整数")


def _int_list(v: str, line_no: int, key: str, *, lo: int | None = None, hi: int | None = None) -> None:
    if not v.replace(" ", ""):
        raise _fail(line_no, f"{key}={v}", "要空格分开的整数表（不能为空）")
    for t in v.split(" "):
        if not re.fullmatch(r"[0-9]+", t):
            raise _fail(line_no, f"{key}={v}", "要空格分开的整数表，混进了非数字")
        if lo is not None and not lo <= int(t) <= (hi if hi is not None else lo):
            raise _fail(line_no, f"{key}={v}", f"里面有元素不在 {lo}..{hi}")


def _value_gate(key: str, v: str, line_no: int) -> None:
    """ocr_conf_check 的逐键值域（对已应用的白名单键生效）。"""
    if key == "OCR_PSM" or key == "OCR_PSM_PAGE":
        _int_in(v, line_no, key, 0, 32)
    elif key == "OCR_MINCONF":
        _int_in(v, line_no, key, 0, 100)
    elif key == "OCR_PSM_BAND" or _BAND_KEY_RE.match(key) or key == "PEND_PSM":
        _int_list(v, line_no, key)
    elif key == "BAND_SCALE":
        _int_in(v, line_no, key, 1, 8)   # 同时是裁片坐标回算的除数，0 会除零
    elif key == "BAND_CUTOFF":
        _int_in(v, line_no, key, 0, 49)
    elif key == "PILL_TH":
        _int_in(v, line_no, key, 0, 255)
    elif key == "PILL_SCALES":
        _int_list(v, line_no, key, lo=1, hi=8)
    elif m := _MODE_KEY_RE.match(key):
        if v not in ("inv", "color"):
            raise _fail(line_no, f"{key}={v}", "只认 inv（反色+硬阈值）或 color（原色）")


def _whitelisted(key: str) -> bool:
    if key in ("OCR_LANG", "OCR_PSM", "OCR_PSM_PAGE", "OCR_MINCONF", "OCR_PSM_BAND",
               "PEND_PSM", "BAND_SCALE", "BAND_CUTOFF", "PILL_TH", "PILL_SCALES"):
        return True
    if _BAND_KEY_RE.match(key) or _MODE_KEY_RE.match(key):
        return True
    return False


def parse_legacy_conf(text: str) -> LegacyConf:
    applied: list[tuple[str, str]] = []
    foreign = 0
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        s = line.lstrip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        if s.startswith("="):
            raise _fail(line_no, s, "的键名是空的（格式是一行一个 KEY=VALUE）")
        if "=" not in s:
            raise _fail(line_no, s, "不是 KEY=VALUE")
        key, _, v = s.partition("=")
        if not _KEY_RE.fullmatch(key):
            raise _fail(line_no, key, "的键名不合法（只许字母、数字、下划线，= 两边不要留空格）")
        v = v.rstrip()
        if key in _CREDENTIAL_KEYS:
            raise _fail(line_no, key,
                        "不许写在这份文件里：它是凭据或离线工具不走网络的后门。"
                        "端点 URL 和 key 只写进 $HOME/Desktop/pdd-vlm.url（权限 600），"
                        "这份配置里只许出现它的路径 VLM_API_URL_FILE")
        if key in _FOREIGN_KEYS:
            foreign += 1
            continue
        if not _whitelisted(key):
            raise LegacyConfError(
                f"第 {line_no} 行的键「{key}」不在名单里。这份文件只管两处 OCR 调用"
                "（认哪几档、怎么预处理、接口怎么问）：OCR_LANG OCR_PSM OCR_PSM_PAGE "
                "OCR_MINCONF OCR_PSM_BAND[_<key>] PEND_PSM BAND_SCALE BAND_CUTOFF "
                "PILL_TH PILL_SCALES PILL_MODE_<key>，外加离线工具的 VLM_ 那批和 PDD_SH。"
                "词表 ALIAS_、区域 REGION_、标定框 PILL_<key>、坐标 COORD_、设备"
                "都在 profile/标定里，写在这里一个字都不会生效"
            )
        _value_gate(key, v, line_no)
        applied.append((key, v))
    return LegacyConf(values=tuple(applied), applied=len(applied), foreign=foreign)


def load_optional_legacy_conf(path: Path) -> LegacyConf | None:
    """B01 的兼容半边：文件不在或读不了 → None（调用方回退默认并记 warning）；
    读得到但内容坏 → LegacyConfError（设备动作前失败，D06）。"""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_legacy_conf(text)
