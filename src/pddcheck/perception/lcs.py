"""最长公共连续字符段（不是 LCS 子序列！）——finder() 的 lcs() 逐行移植（pdd.sh:470-483）。

返回 (长度, 在 hay 里的起点)。同一长度取**最先**出现的位置（旧 DP 用严格大于更新 best）。
overlap 语义 = 这里的长度；它与置信度不同域，禁止混算（契约 §3.4）。
"""

from __future__ import annotations


def longest_common_span(hay: str, needle: str) -> tuple[int, int]:
    """hay/needle 都应是规范化后的文本。空 needle → (0, 0)。"""
    if not hay or not needle:
        return 0, 0
    best, at = 0, 0
    prev = [0] * (len(needle) + 1)
    for i in range(1, len(hay) + 1):
        cur = [0] * (len(needle) + 1)
        for j in range(1, len(needle) + 1):
            if hay[i - 1] == needle[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:          # 严格大于：并列时保留最早的位置
                    best, at = cur[j], i - cur[j]
        prev = cur
    return best, at
