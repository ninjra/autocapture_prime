from .base import OcrEngine, OcrSpan
from .paddle_engine import PaddleOcrEngine
from .tesseract_engine import TesseractOcrEngine

__all__ = ["OcrEngine", "OcrSpan", "PaddleOcrEngine", "TesseractOcrEngine"]
