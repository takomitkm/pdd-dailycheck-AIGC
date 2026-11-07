"""CLI 组合根（T14）。

- exits.py：退出码合同（旧 0/1/2/3/4/5/6/69/73/78 + 新 75），与终态效果映射；
- app.py：子命令装配。离线命令（check-config/doctor/replay/version）用离线能力集，
  拿不到 DevicePort；run 才需要设备能力（I03）。
"""

from pddcheck.cli.exits import EXIT_TABLE, ExitCode, exit_for_outcome
from pddcheck.cli.app import main

__all__ = ["EXIT_TABLE", "ExitCode", "exit_for_outcome", "main"]
