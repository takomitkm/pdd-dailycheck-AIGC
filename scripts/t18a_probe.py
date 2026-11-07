"""T18a 早期通道资格探针（只读）：连接/采集/焦点/层级，绝不 tap/swipe/领取。

用法：
  python scripts/t18a_probe.py --serial 192.168.1.110:16132 --out reports/t18a
产出 reports/t18a/channel-report.json + 截图/XML 工件。只做读操作。
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import time
from pathlib import Path


def adb(serial: str, *args: str, timeout: float = 30.0, binary: bool = True):
    p = subprocess.run(["adb", "-s", serial, *args], capture_output=True, timeout=timeout)
    return p.returncode, (p.stdout if binary else p.stdout.decode("utf-8", "replace")), \
        p.stderr.decode("utf-8", "replace")


def png_size(data: bytes):
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "kind": "t18a-channel-probe", "serial": a.serial,
              "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "steps": {}}

    # 1) 连接态
    t0 = time.monotonic()
    rc, state, err = adb(a.serial, "get-state", binary=False)
    report["steps"]["get_state"] = {"rc": rc, "state": state.strip(), "err": err.strip(),
                                    "ms": round((time.monotonic() - t0) * 1000)}
    if rc != 0 or state.strip() != "device":
        report["verdict"] = "unavailable"
        (out / "channel-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
        print(json.dumps(report["steps"], ensure_ascii=False))
        return 2

    # 2) 焦点（只读）
    t0 = time.monotonic()
    rc, win, err = adb(a.serial, "shell", "dumpsys", "window", binary=False)
    focus = ""
    for line in win.splitlines():
        if "mCurrentFocus" in line:
            focus = line.strip()
            break
    report["steps"]["focus"] = {"rc": rc, "mCurrentFocus": focus,
                                "ms": round((time.monotonic() - t0) * 1000)}

    # 3) 截图（只读）
    t0 = time.monotonic()
    rc, png, err = adb(a.serial, "exec-out", "screencap", "-p")
    png_path = out / "screen.png"
    if rc == 0 and png:
        png_path.write_bytes(png)
    report["steps"]["screencap"] = {"rc": rc, "bytes": len(png),
                                    "size": png_size(png) if png else None,
                                    "ms": round((time.monotonic() - t0) * 1000)}

    # 4) 层级（只读）——真机坑：/dev/tty 可能返回空，回退 dump 到文件再 cat
    t0 = time.monotonic()
    rc, xml, err = adb(a.serial, "shell", "uiautomator", "dump", "/dev/tty", binary=False)
    xml_text = xml if "<hierarchy" in xml else ""
    if not xml_text:
        adb(a.serial, "shell", "uiautomator", "dump", "/sdcard/pddcheck-probe.xml", binary=False)
        rc2, xml2, _ = adb(a.serial, "exec-out", "cat", "/sdcard/pddcheck-probe.xml", binary=False)
        xml_text = xml2 if "<hierarchy" in xml2 else ""
        adb(a.serial, "shell", "rm", "-f", "/sdcard/pddcheck-probe.xml", binary=False)
    if xml_text:
        (out / "hierarchy.xml").write_text(xml_text, encoding="utf-8")
    report["steps"]["hierarchy"] = {"rc": rc, "chars": len(xml_text),
                                    "has_hierarchy": bool(xml_text),
                                    "ms": round((time.monotonic() - t0) * 1000)}

    # 判定：连接通 + 能拿到一张可解码的 PNG 即为通道合格（焦点/层级仅供参考）
    ok = (report["steps"]["get_state"]["rc"] == 0
          and report["steps"]["screencap"]["size"] is not None)
    report["verdict"] = "channel_ok" if ok else "channel_degraded"
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (out / "channel-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], **report["steps"]}, ensure_ascii=False))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
