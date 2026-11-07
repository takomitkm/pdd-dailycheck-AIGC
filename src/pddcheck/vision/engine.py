"""OCR 引擎适配器（T07.4/T16）：两种后端产出同一 TSV 形状，交给同一 parse_tsv。

- TesseractEngine：包装 run_tesseract_tsv（单实例独占、超时回收）；
- RapidOcrEngine：把 rapidocr 的 [box, text, score] 检测框转成标准 TSV 行
  （level=5 词行；conf ×100 取整），使 perception 无需为后端分叉；
  单行含多个按钮时不伪造子串点——每个检测框就是一个词，span 并集逻辑不变；
- EngineLease：按 engine_id 独占（同一 id 第二个实例报错），close 释放。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pddcheck.domain import ReadStatus
from pddcheck.vision.tesseract import TsvResult, TesseractConfig, run_tesseract_tsv


@dataclass(frozen=True, slots=True)
class EngineInfo:
    engine_id: str            # tesseract-cli | rapidocr-onnx
    version: str | None
    model_hash: str | None


class OcrEngine(Protocol):
    def info(self) -> EngineInfo: ...
    def recognize(self, image: Path | bytes, psm: int) -> TsvResult: ...


class TesseractEngine:
    def __init__(self, config: TesseractConfig = TesseractConfig(), *,
                 version: str | None = None, runner=None) -> None:
        self._config = config
        self._version = version
        self._runner = runner

    def info(self) -> EngineInfo:
        return EngineInfo("tesseract-cli", self._version, None)

    def recognize(self, image: Path | bytes, psm: int) -> TsvResult:
        if isinstance(image, bytes):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
                fh.write(image)
                tmp = Path(fh.name)
            try:
                return run_tesseract_tsv(tmp, psm, self._config,
                                         engine_version=self._version, runner=self._runner)
            finally:
                tmp.unlink(missing_ok=True)
        return run_tesseract_tsv(Path(image), psm, self._config,
                                 engine_version=self._version, runner=self._runner)


_TSV_HEADER = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
               "left\ttop\twidth\theight\tconf\ttext")


def detections_to_tsv(detections) -> str:
    """rapidocr 结果 → 标准 TSV。每个检测框一行 level=5；box 为四点多边形，取外接矩形。"""
    rows = [_TSV_HEADER]
    blk = 1
    for i, item in enumerate(detections or [], start=1):
        box, text, score = item[0], item[1], item[2]
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        left, top = int(min(xs)), int(min(ys))
        width, height = int(max(xs) - min(xs)), int(max(ys) - min(ys))
        conf = int(round(float(score) * 100)) if float(score) <= 1.0 else int(round(float(score)))
        text = str(text).replace("\t", " ").replace("\n", " ").strip()
        if not text:
            continue
        rows.append(f"5\t1\t{blk}\t1\t{i}\t1\t{left}\t{top}\t{width}\t{height}\t{conf}\t{text}")
    return "\n".join(rows) + "\n"


class RapidOcrEngine:
    def __init__(self, *, engine=None, version: str | None = None,
                 model_hash: str | None = None) -> None:
        self._engine = engine                 # 注入；None 时懒加载 rapidocr_onnxruntime
        self._version = version
        self._model_hash = model_hash

    def _ensure(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR   # 惰性：缺库时才报错
            self._engine = RapidOCR()
        return self._engine

    def info(self) -> EngineInfo:
        return EngineInfo("rapidocr-onnx", self._version, self._model_hash)

    def recognize(self, image: Path | bytes, psm: int) -> TsvResult:
        import time
        t0 = time.monotonic()
        try:
            engine = self._ensure()
            result, _ = engine(str(image) if isinstance(image, (str, Path))
                               else _bytes_to_tmp(image))
        except Exception as exc:              # 缺库/模型/解码失败：INVALID，不伪装空
            return TsvResult(ReadStatus.INVALID, "", f"rapid_{type(exc).__name__}",
                             None, str(exc)[:400], time.monotonic() - t0, self._version)
        return TsvResult(ReadStatus.OK, detections_to_tsv(result), None, 0, "",
                         time.monotonic() - t0, self._version)


def _bytes_to_tmp(data: bytes) -> str:
    import tempfile
    fh = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fh.write(data)
    fh.close()
    return fh.name


_LEASED: set[str] = set()


class EngineLease:
    """按 engine_id 独占：同 id 第二个实例报错（契约：一个引擎实例独占）。"""

    def __init__(self, engine: OcrEngine) -> None:
        self.engine = engine
        self._id = engine.info().engine_id
        if self._id in _LEASED:
            raise RuntimeError(f"引擎 {self._id} 已被占用（单实例独占）")
        _LEASED.add(self._id)

    def close(self) -> None:
        _LEASED.discard(self._id)

    def __enter__(self) -> "EngineLease":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
