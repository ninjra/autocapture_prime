from __future__ import annotations

from PIL import Image

from autocapture_prime.ocr.base import OcrSpan

from .base import UiElement


class OmniParserEngine:
    """Optional engine; requires explicit allow flag and local dependency."""

    def __init__(self, allow_agpl: bool) -> None:
        self.allow_agpl = bool(allow_agpl)

    def run(self, image: Image.Image, ocr_spans: list[OcrSpan]) -> list[UiElement]:
        if not self.allow_agpl:
            return []
        try:
            import omniparser  # type: ignore # noqa: F401
        except Exception:
            return []
        # Integration placeholder; in this repo we normalize to UiElement in a
        # deterministic local backend first.
        _ = image
        _ = ocr_spans
        return []
