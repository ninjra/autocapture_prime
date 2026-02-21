"""Ingest normalizer and OCR engine."""

from __future__ import annotations

from typing import Any

from autocapture.ingest.ocr_basic import ocr_tokens_from_image
from autocapture.ingest.spans import Span, build_span


def normalize_bbox(bbox: tuple[int, int, int, int], width: int, height: int) -> dict[str, float]:
    x, y, w, h = bbox
    return {
        "x0": x / width,
        "y0": y / height,
        "x1": (x + w) / width,
        "y1": (y + h) / height,
    }


def normalize_bbox_xyxy(bbox: tuple[int, int, int, int], width: int, height: int) -> dict[str, float]:
    x0, y0, x1, y1 = bbox
    return {
        "x0": x0 / width,
        "y0": y0 / height,
        "x1": x1 / width,
        "y1": y1 / height,
    }


class OcrEngine:
    def extract(self, image) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        width, height = image.size
        for token in ocr_tokens_from_image(image):
            if not token.text or not token.text.strip():
                continue
            results.append({"text": token.text, "bbox": normalize_bbox_xyxy(token.bbox, width, height)})
        return results


class IngestNormalizer:
    def normalize(self, text: str, bbox: dict[str, float] | None, source: dict[str, Any]) -> Span:
        return build_span(text, bbox, source)


def create_ocr_engine(plugin_id: str) -> OcrEngine:
    return OcrEngine()
