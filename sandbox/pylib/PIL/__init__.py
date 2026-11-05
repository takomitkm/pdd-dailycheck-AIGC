# -*- coding: utf-8 -*-
"""最小 PIL 兼容层（PNG 专用）——沙箱基础设施，不是生产依赖。

为什么存在：本地沙箱（WSL Ubuntu 26.04, python3.14）没有 Pillow、按任务边界
不许联网安装；pdd.sh 的 band/pill 裁片路径在沙箱里用到的 PIL API 只有这一小撮。
对齐真实 PIL 的使用形状：`from PIL import Image` 得到的是**模块**，
`Image.open` / `Image.new` / `Image.LANCZOS` 都从模块取，类本体是 Image.Image。

实现原则：像素真的按 PNG 解、真的算、真的存；不支持的就抛异常，绝不静默造
假图。判定链不经过像素（OCR 桩按文件名回 TSV，裁片只要求「几何真实 + 文件
非空」），但兼容层按真实图像处理实现，换真 OCR 也不在这里先撒谎。
"""
from . import Image
from . import ImageOps

__version__ = "0.1-pdd-sandbox-min"

__all__ = ["Image", "ImageOps", "__version__"]
