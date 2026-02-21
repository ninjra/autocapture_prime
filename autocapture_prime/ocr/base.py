from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class OcrSpan:
    text: str
    confidence: float
    bbox: tuple[int, int, int, int]
    reading_order: int
    language: str = ""


class OcrEngine(Protocol):
    def run(self, image: Image.Image, rois: list[tuple[int, int, int, int]] | None = None) -> list[OcrSpan]:
        ...
