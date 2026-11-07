"""单次推送适配（T10，D07/I11）。

- 端点从注入的文件读第一行（旧 PUSH_URL_FILE 口径）；文件不在/读不了 = 没配推送，
  一次 attempt 都不发，业务照跑；
- 一次 attempt：传输超时/HTTP 非 2xx/响应非 JSON/业务 code≠0 全是失败分型，
  绝不自动重发（I11）；失败不改业务 rc（调用方只落 delivery 状态）；
- 脱敏：端点值/token 不进异常文本、不进 DeliveryResult（只有分类与 stderr 尾巴）。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class DeliveryStatus(StrEnum):
    SENT = "sent"                          # HTTP 2xx 且业务 code==0
    HTTP_ERROR = "http_error"              # 2xx 之外
    BUSINESS_NONZERO = "business_nonzero"  # 2xx 但 JSON code≠0 / 解析不出 code
    NETWORK_ERROR = "network_error"        # 连接/超时/DNS
    NO_ENDPOINT = "no_endpoint"            # 未配置：0 次发送
    SKIPPED = "skipped"                    # dry-run 等刻意不发送：0 次发送


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    status: DeliveryStatus
    attempts: int                          # 只会是 0 或 1
    http_code: int | None
    error_tail: str                        # ≤200 字符；端点值已脱敏


def read_endpoint_file(path: Path) -> str | None:
    """端点文件第一行（旧口径）；不在/读不了 → None。值绝不进日志/异常。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    first = text.splitlines()[0].strip() if text.splitlines() else ""
    return first or None


class NotificationSender:
    """单次 GET（ServerChan 形状：curl -G --data-urlencode title=/desp=）。"""

    def __init__(self, timeout_s: float = 15.0, transport=None) -> None:
        self._timeout_s = timeout_s
        self._transport = transport        # 测试注入：(url, timeout) -> (http_code, body_text)

    def send(self, endpoint: str | None, title: str, desp: str) -> DeliveryResult:
        if not endpoint:
            return DeliveryResult(DeliveryStatus.NO_ENDPOINT, 0, None, "")
        url = endpoint + "?" + urllib.parse.urlencode(
            {"title": title, "desp": desp}, encoding="utf-8")
        code: int | None
        body = ""
        try:
            if self._transport is not None:
                code, body = self._transport(url, self._timeout_s)
            else:
                req = urllib.request.Request(url)   # 值已在 query；不带任何多余头
                with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                    code = resp.status
                    body = resp.read(4096).decode("utf-8", errors="replace")
        except Exception as exc:                    # 网络/超时/DNS——端点值脱敏
            return DeliveryResult(DeliveryStatus.NETWORK_ERROR, 1, None,
                                  _redact(str(exc), endpoint)[:200])
        if code is None or not 200 <= code < 300:
            return DeliveryResult(DeliveryStatus.HTTP_ERROR, 1, code,
                                  _redact(body[:200], endpoint))
        try:
            payload = json.loads(body)
            business = int(payload.get("code", 0))
        except (json.JSONDecodeError, ValueError, TypeError):
            business = -1                           # 非 JSON = 解析不出 code（D07 严谨半边）
        if business != 0:
            return DeliveryResult(DeliveryStatus.BUSINESS_NONZERO, 1, code,
                                  _redact(body[:200], endpoint))
        return DeliveryResult(DeliveryStatus.SENT, 1, code, "")


def _redact(text: str, endpoint: str) -> str:
    """错误尾巴里的端点串（含 token）替换成占位——脱敏是硬要求（契约 §10）。"""
    if endpoint and endpoint in text:
        text = text.replace(endpoint, "<endpoint>")
    for part in endpoint.split("/"):
        if len(part) >= 16 and part in text:        # token 片段级别也打
            text = text.replace(part, "<token>")
    return text
