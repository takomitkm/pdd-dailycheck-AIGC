"""配置错误：装载失败必须发生在任何设备动作之前（D06）。"""

from __future__ import annotations

from pddcheck.domain.errors import DomainError


class ConfigError(DomainError):
    """profile/TOML 装载或校验失败。"""


class LegacyConfError(DomainError):
    """旧 pdd-ocr.conf 解析失败（带行号）。"""
