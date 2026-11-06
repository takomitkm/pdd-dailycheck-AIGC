r"""文本规范化：与 finder() 的 NOISE 正则逐字符一致（pdd.sh:460）。

保留 \w（含数字/下划线/Unicode 字母）与显式 CJK 区段，其余全剥。
「立即 点 亮」→「立即点亮」；OCR 把字间塞的空格/标点都这样抹掉。
"""

from __future__ import annotations

import re

NOISE = re.compile(r"[^\w\u4e00-\u9fff\u3400-\u4dbf]+")


def normalize(text: str | None) -> str:
    """与旧 norm() 一致：None/空串 → 空串；否则剥噪声字符。"""
    return NOISE.sub("", text or "")
