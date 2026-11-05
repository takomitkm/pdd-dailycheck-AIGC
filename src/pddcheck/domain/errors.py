"""错误分类：区分「没找到」「读坏了」「依据过期」「结果未知」（契约 §3.2）。"""

from __future__ import annotations


class DomainError(Exception):
    """domain 层错误基类；各模块可派生自己的子类但必须归入以下语义。"""


class InvalidDomain(DomainError):
    """构造了非法对象（缺字段、越界、形状不对）。"""


class ReadFailure(DomainError):
    """采集/识别基础设施失败。空结果（ABSENT）不是本错误。"""


class StaleObservation(DomainError):
    """动作依据已过期（epoch/新鲜度/几何不匹配），必须重新观察。"""


class UnknownExecution(DomainError):
    """底层动作已发出但结果未知；禁止据此自动重发。"""


class PolicyViolation(DomainError):
    """动作策略拒绝（焦点门禁/白名单/坐标来源/人工兑换界限）。"""
