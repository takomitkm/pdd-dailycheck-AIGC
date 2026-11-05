"""pddcheck —— 单台 Android 每日签到的模块化实现（refactor-v2）。

公共合同：docs/refactor-v2/architecture-contracts.md。
包 import 时不得连接设备、读取端点、加载模型或读取环境配置（契约 §1）；
真实适配器只在 cli/bootstrap 组装。
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
