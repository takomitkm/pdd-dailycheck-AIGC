"""Tesseract CLI 适配（T07）：单次子进程、结果三态、stderr 不丢。

契约对齐：
- 一次底层调用；TIMEOUT/INVALID/UNAVAILABLE 是显式状态，绝不伪装成「没找到」
  （契约 §3.2；旧脚本丢弃 stderr 是 B 类教训）；
- 引擎元数据（版本）随结果返回，参与缓存键与工件溯源（契约 §7/§9）；
- 无任何自动重试——失败就是失败，重试是 workflow 层的显式预算。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from pddcheck.domain import ReadStatus


class TesseractError(Exception):
    """适配器自身的问题（二进制不存在等），区别于单次识别的失败状态。"""


@dataclass(frozen=True, slots=True)
class TesseractConfig:
    binary: str = "tesseract"
    lang: str = "chi_sim+eng"
    timeout_s: float = 8.0


@dataclass(frozen=True, slots=True)
class TsvResult:
    status: ReadStatus
    tsv_text: str                    # OK 时是完整 TSV；失败时空串
    error_code: str | None           # INVALID/TIMEOUT/UNAVAILABLE 时非空
    returncode: int | None
    stderr_tail: str                 # 恒收集（≤400 字符），成功时通常为空
    duration_s: float
    engine_version: str | None       # 由探测填充；未知为 None


def tesseract_version(config: TesseractConfig = TesseractConfig()) -> str | None:
    """`tesseract --version` 首行（旧 status 的口径）。拿不到 → None（调用方定 78 语义）。"""
    try:
        out = subprocess.run(
            [config.binary, "--version"],
            capture_output=True, text=True, timeout=10.0, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = (out.stdout or out.stderr or "").splitlines()
    return first[0].strip() if first else None


def run_tesseract_tsv(
    image_path: Path,
    psm: int,
    config: TesseractConfig = TesseractConfig(),
    *,
    engine_version: str | None = None,
    runner=None,
) -> TsvResult:
    """对一张图跑一次 `tesseract <img> stdout -l <lang> --psm <psm> tsv`。

    runner 参数供测试注入假进程；生产路径是 subprocess.run 的直接封装。
    """
    import time

    argv = [config.binary, str(image_path), "stdout", "-l", config.lang,
            "--psm", str(psm), "tsv"]
    t0 = time.monotonic()
    try:
        if runner is not None:
            completed = runner(argv, config.timeout_s)
        else:
            completed = subprocess.run(
                argv, capture_output=True, text=True,
                timeout=config.timeout_s, check=False,
            )
    except subprocess.TimeoutExpired:
        return TsvResult(ReadStatus.TIMEOUT, "", "ocr_timeout", None,
                         f"超过 {config.timeout_s}s 未完成", config.timeout_s, engine_version)
    except OSError as exc:
        return TsvResult(ReadStatus.UNAVAILABLE, "", "ocr_missing", None,
                         str(exc)[:400], 0.0, engine_version)
    duration = time.monotonic() - t0
    stdout = completed.stdout or ""
    stderr = (completed.stderr or "")[-400:]
    rc = completed.returncode
    if rc != 0:
        # 识别失败不是「没找到」：INVALID + stderr 尾巴，绝不假装空结果
        return TsvResult(ReadStatus.INVALID, "", f"ocr_rc_{rc}", rc, stderr, duration, engine_version)
    return TsvResult(ReadStatus.OK, stdout, None, 0, stderr, duration, engine_version)
