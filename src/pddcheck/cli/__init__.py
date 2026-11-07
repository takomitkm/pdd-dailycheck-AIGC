"""CLI 组合根（T14）。

导出用惰性 `__getattr__`：避免 `python -m pddcheck.cli.app` 时包 `__init__`
提前 import app 触发 runpy 的「already in sys.modules」警告。
"""

__all__ = ["EXIT_TABLE", "ExitCode", "exit_for_outcome", "main"]


def __getattr__(name: str):
    if name in ("EXIT_TABLE", "ExitCode", "exit_for_outcome"):
        from pddcheck import exits
        return getattr(exits, name)
    if name == "main":
        from pddcheck.cli.app import main
        return main
    raise AttributeError(name)
