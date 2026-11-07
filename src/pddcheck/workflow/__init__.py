"""workflow：流程判定（T11）。纯函数——无 IO、无 sleep、无环境读取（契约 §4）。

verify.py：verify_light 的决策核（设备动作——BACK/点胶囊/收浮层——由执行器做，
这里只按「观察记录序列」判结局）。check_before.py：点「立即点亮」前的终态决策核。
"""

from pddcheck.workflow.verify import (
    VerifyObservation,
    VerifyStage,
    VerifyOutcome,
    verify_light_decision,
)
from pddcheck.workflow.check_before import (
    CheckBeforeKind,
    CheckBeforeOutcome,
    check_done_before_decision,
)

__all__ = [
    "VerifyObservation",
    "VerifyStage",
    "VerifyOutcome",
    "verify_light_decision",
    "CheckBeforeKind",
    "CheckBeforeOutcome",
    "check_done_before_decision",
]
