"""evidence：不可变工件与事件流（T09，契约 §10）。

- artifacts.py：内容寻址存储（sha256 = 路径），同内容同址、绝不覆盖；
- events.py：JSONL 事件流（seq 单调、崩溃半截行容错、redact 钩子）。
"""

from pddcheck.evidence.artifacts import ArtifactCollision, ArtifactStore, ArtifactRef
from pddcheck.evidence.events import EventLog, RunEvent

__all__ = ["ArtifactCollision", "ArtifactStore", "ArtifactRef", "EventLog", "RunEvent"]
