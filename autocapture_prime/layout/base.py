from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image

from autocapture_prime.ocr.base import OcrSpan


@dataclass(frozen=True)
class UiElement:
    element_id: str
    type: str
    bbox: tuple[int, int, int, int]
    confidence: float
    label: str = ""
    text: str = ""
    parent_id: str = ""


class LayoutEngine(Protocol):
    def run(self, image: Image.Image, ocr_spans: list[OcrSpan]) -> list[UiElement]:
        ...
