"""vision：OCR 引擎适配（T07）。识别只读图像，不访问设备、不决定点击（契约 §1）。

tesseract.py：子进程包装——stderr/退出码/耗时全部留痕（旧脚本把它们丢掉是 B 类教训）；
batch.py：对私有真图语料的整页 OCR 批处理（psm11/psm6），产出 raw TSV 工件。
"""

from pddcheck.vision.tesseract import (
    TesseractConfig,
    TesseractError,
    TsvResult,
    ReadStatus,
    run_tesseract_tsv,
    tesseract_version,
)

__all__ = [
    "TesseractConfig",
    "TesseractError",
    "TsvResult",
    "ReadStatus",
    "run_tesseract_tsv",
    "tesseract_version",
]
