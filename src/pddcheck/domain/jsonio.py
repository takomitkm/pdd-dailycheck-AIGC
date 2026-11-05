"""跨进程 JSON 信封（契约：顶层 schema_version、枚举用稳定字符串、未知键拒绝）。

- ``jsonable(obj)``：dataclass→dict（带 ``_type`` 标签），Enum→value，tuple→list。
- ``envelope(obj)``：``{"schema_version", "type", "data"}``。
- ``from_envelope(data, cls)``：严格校验信封；字段名不匹配、缺键、多键一律报错。
- ``@serializable``：注册可反序列化类型，类必须自带 ``from_jsonable(d)``；
  嵌套对象在各自 ``from_jsonable`` 里递归重建，不走通用反射。

注意：``strict_fields`` 永远忽略 ``_type`` 标签（它是类型标签，不是字段）。
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any, Mapping, TypeVar

from pddcheck.domain.errors import InvalidDomain
from pddcheck.domain.version import SCHEMA_VERSION

_PRIMITIVE = (str, int, float, bool)
T = TypeVar("T")

_JSON_TYPES: dict[str, type] = {}


def serializable(cls: type[T]) -> type[T]:
    """注册一个带 from_jsonable 的 domain 类型，供 from_envelope 按名解码。"""
    if not callable(getattr(cls, "from_jsonable", None)):
        raise InvalidDomain(f"{cls.__name__} 标了 @serializable 但没有 from_jsonable")
    _JSON_TYPES[cls.__name__] = cls
    return cls


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, _PRIMITIVE):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: dict[str, Any] = {"_type": type(value).__name__}
        for f in dataclasses.fields(value):
            out[f.name] = jsonable(getattr(value, f.name))
        return out
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    raise InvalidDomain(f"不可序列化类型：{type(value)!r}")


def envelope(obj: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": type(obj).__name__,
        "data": jsonable(obj),
    }


def strict_fields(cls: type, data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise InvalidDomain(f"{cls.__name__} 反序列化输入必须是映射")
    expected = {f.name for f in dataclasses.fields(cls)}
    got = set(data.keys())
    unknown = got - expected - {"_type"}
    missing = expected - got
    if unknown or missing:
        raise InvalidDomain(f"{cls.__name__} 字段不匹配：缺 {sorted(missing)}，多 {sorted(unknown)}")
    return {name: data[name] for name in expected}


def from_envelope(data: Mapping[str, Any], cls: type[T]) -> T:
    if not isinstance(data, Mapping):
        raise InvalidDomain("信封必须是映射")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise InvalidDomain(f"schema_version 不匹配：{data.get('schema_version')!r} ≠ {SCHEMA_VERSION}")
    if data.get("type") != cls.__name__:
        raise InvalidDomain(f"信封 type {data.get('type')!r} ≠ {cls.__name__}")
    return cls.from_jsonable(data["data"])  # type: ignore[return-value]
