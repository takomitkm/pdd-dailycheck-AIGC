"""T05：配置与 profile（契约 §9）。

- profile.py：冻结数据模型 + 内建默认 + 严格 TOML 装载（未知键/坏值在设备动作前失败，D06）。
- legacy_conf.py：旧 pdd-ocr.conf 的只读解析器，名单/豁免/值域与 load_ocr_conf+ocr_conf_check
  逐条对齐（B01：文件不可读的回退决定在调用方，解析器只吃文本）。
"""

from pddcheck.config.errors import ConfigError, LegacyConfError
from pddcheck.config.profile import (
    DeviceConfig,
    FlowConfig,
    OcrConfig,
    Profile,
    TargetSpec,
    defaults,
    load_profile,
)
from pddcheck.config.legacy_conf import (
    LegacyConf,
    LegacyConfError,
    load_optional_legacy_conf,
    parse_legacy_conf,
)

__all__ = [
    "ConfigError",
    "LegacyConfError",
    "LegacyConf",
    "DeviceConfig",
    "FlowConfig",
    "OcrConfig",
    "Profile",
    "TargetSpec",
    "defaults",
    "load_profile",
    "parse_legacy_conf",
    "load_optional_legacy_conf",
]
