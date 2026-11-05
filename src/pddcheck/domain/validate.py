"""字段校验助手：所有 domain 对象在构造时验证，坏数据当场拒绝（契约 §3）。"""

from __future__ import annotations

import re
from typing import Iterable

from pddcheck.domain.errors import InvalidDomain

_SHA256 = re.compile(r"[0-9a-f]{64}")


def require_int(value: object, name: str, *, minimum: int | None = None) -> int:
    # type(v) is int：把 bool/float 挡在外面（True 是 int 子类，但不是合法坐标）。
    if type(value) is not int:
        raise InvalidDomain(f"{name} 必须是 int，得到 {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise InvalidDomain(f"{name} 必须 >= {minimum}，得到 {value}")
    return value  # type: ignore[return-value]


def require_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidDomain(f"{name} 必须是非空字符串")
    return value


def require_opt_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    return require_str(value, name)


def require_sha256(value: object, name: str) -> str:
    require_str(value, name)
    if not _SHA256.fullmatch(value):  # type: ignore[union-attr]
        raise InvalidDomain(f"{name} 必须是小写 sha256 hex（64 位）")
    return value  # type: ignore[return-value]


def require_enum(value: object, name: str, enum_cls: type) -> object:
    if not isinstance(value, enum_cls):
        raise InvalidDomain(f"{name} 必须是 {enum_cls.__name__}，得到 {value!r}")
    return value


def require_no_duplicates(pairs: Iterable[tuple[str, str]], name: str) -> None:
    seen: set[str] = set()
    for key, _ in pairs:
        if not key:
            raise InvalidDomain(f"{name} 的键必须非空")
        if key in seen:
            raise InvalidDomain(f"{name} 有重复键：{key}")
        seen.add(key)
