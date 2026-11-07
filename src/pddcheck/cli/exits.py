"""退出码（转发）——实现已移到顶层 pddcheck.exits，避免 workflow 依赖 cli。

保留本模块仅为向后兼容的导入路径。
"""

from pddcheck.exits import EARLY_EXIT, EXIT_TABLE, SILENT_EXIT, ExitCode, exit_for_outcome

__all__ = ["EARLY_EXIT", "EXIT_TABLE", "SILENT_EXIT", "ExitCode", "exit_for_outcome"]
