# T18a 早期通道资格（真机只读）— 2026-11-07 10:53

> 设备：`192.168.1.110:16132`（无线 adb，状态 device）
> 只读探针：`scripts/t18a_probe.py`（连接/焦点/截图/层级，**不 tap/swipe/领取**）
> 执行机：本机 Windows adb；OCR 计时在部署目标 **deb-h61**（Debian 13 / Python 3.13.5）

## 通道资格结论：**channel_ok**

| 步骤 | 结果 | 耗时 |
|---|---|---|
| get-state | device | 78 ms |
| 焦点 | `com.android.launcher3/Launcher` | 282 ms |
| screencap | 720×1280 PNG，881 KB | 750 ms |
| uiautomator dump | 11932 字符 | 3484 ms（文件回退） |

## 真机坑（已修）

1. **`uiautomator dump /dev/tty` 在本机返回 0 字符**——真机必须 `dump /sdcard/x.xml`
   再 `exec-out cat`。已修 `AdbDevice.read_hierarchy`（先试 /dev/tty，空则回退文件法，
   读完 `rm` 清理不留垃圾），并有测试兜底。这是 T18a 要抓的典型真机差异。
2. 桌面截图正常 720×1280（10-29 语料里 1280×720 的黑帧确属熄屏，不是方向问题）。

## 真实 OCR 耗时（部署目标 h61，同一张真机桌面截图）

- psm6：runs [2.274, 2.291, 2.364] → **p50 2.29 s**
- psm11：runs [2.155, 2.150, 2.192] → **p50 2.16 s**
- 参考：语料批处理（WSL 宿主）p50 1.06/1.41 s；h61 桌面图标密集页更慢，属预期。
- 含义：T16 的 -87% 调用减少在真机链路上能直接折成时间（少两次全页 OCR ≈ 省 4–5 s/帧）。

## 未做（等授权/后续）

- 真机**业务动作**（点亮/领取/兑换）本轮一律未执行；仅只读。
- 端到端实跑需要把 bootstrap 的 device 换成 AdbDevice、engine 换成 TesseractEngine，
  并在 h61 上跑（h61 已有 adb+tesseract）。这会在真实链路点一次「立即点亮」，
  待用户明确同意后再做（并先与每日定时器错峰）。
