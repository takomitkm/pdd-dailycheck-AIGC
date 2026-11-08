"""T14/T22：`pddcheck run` 接线——无 --device 报 69；装配路径用假适配器跑通。"""

from __future__ import annotations

import json

from pddcheck.cli.app import main
from pddcheck.domain import ExecutionStatus, ReadStatus
from pddcheck.exits import ExitCode
from pddcheck.vision.tesseract import TsvResult


def test_run_without_device_returns_69(capsys):
    assert main(["run"]) == int(ExitCode.NO_ADB)
    assert "--device" in capsys.readouterr().err


def test_run_wires_adapters_and_maps_outcome(tmp_path, monkeypatch):
    """用假 AdbDevice/TesseractEngine/lease 走通 _cmd_run，验证退出码与摘要。"""
    import pddcheck.device.adb as adb_mod
    import pddcheck.vision.engine as eng_mod
    import pddcheck.notify.sender as sender_mod

    ROW1 = "5\t1\t1\t1\t1\t1\t100\t880\t100\t40\t92\t抽福袋\n5\t1\t2\t1\t2\t1\t100\t1000\t120\t40\t91\t立即点亮\n5\t1\t3\t1\t3\t1\t100\t200\t400\t40\t90\t9天内点亮4次必得\n"
    ROW2 = ROW1.replace("4次必得", "3次必得")

    class FakeAdb:
        def __init__(self, serial, *, home_activity=None):
            self.serial = serial
            self.state_epoch = 0
            self.home_activity = home_activity
        def connect(self): return "device"
        def read_hierarchy(self): return "<hierarchy></hierarchy>"
        def screenshot_bytes(self): return b"png"
        def execute(self, intent, point=None):
            from pddcheck.domain import ActionReceipt
            return ActionReceipt(intent.action_id, ExecutionStatus.ACKNOWLEDGED, 1, 1)

    class FakeEngine:
        def __init__(self, *a, **k): self.n = 0
        def info(self): return None
        def recognize(self, image, psm):
            t = ROW1 if self.n == 0 else ROW2
            self.n += 1
            return TsvResult(ReadStatus.OK, t, None, 0, "", 0.0, "x")

    class FakeLease:
        def release(self): pass

    monkeypatch.setattr(adb_mod, "AdbDevice", FakeAdb)
    monkeypatch.setattr(eng_mod, "TesseractEngine", FakeEngine)
    monkeypatch.setattr(sender_mod, "read_endpoint_file", lambda p: None)
    # _cmd_run 内部 from pddcheck.storage import acquire_run_lease → 打补丁到包导出
    import pddcheck.storage as st_mod
    monkeypatch.setattr(st_mod, "acquire_run_lease", lambda *a, **k: FakeLease())

    monkeypatch.setenv("HOME", str(tmp_path))
    rc = main(["run", "--device", "FAKE123"])
    assert rc == int(ExitCode.OK)
