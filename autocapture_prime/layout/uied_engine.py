from __future__ import annotations

import hashlib

from PIL import Image

from autocapture_prime.ocr.base import OcrSpan

from .base import UiElement


class UIEDEngine:
    """Local layout approximation using OCR spans when UIED is unavailable."""

    def run(self, image: Image.Image, ocr_spans: list[OcrSpan]) -> list[UiElement]:
        _ = image
        elements: list[UiElement] = []
        for span in ocr_spans:
            seed = f"{span.text}|{span.bbox[0]}|{span.bbox[1]}|{span.bbox[2]}|{span.bbox[3]}"
            element_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
            elements.append(
                UiElement(
                    element_id=element_id,
                    type="TEXT",
                    bbox=span.bbox,
                    confidence=span.confidence,
                    text=span.text,
                    label="ocr_text",
                )
            )
        return elements
