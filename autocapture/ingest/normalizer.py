"""Ingest normalizer and OCR engine."""

from __future__ import annotations

from typing import Any

from autocapture.ingest.spans import Span, build_span


def normalize_bbox(bbox: tuple[int, int, int, int], width: int, height: int) -> dict[str, float]:
    x, y, w, h = bbox
    return {
        "x0": x / width,
        "y0": y / height,
        "x1": (x + w) / width,
        "y1": (y + h) / height,
    }


class OcrEngine:
    def extract(self, image) -> list[dict[str, Any]]:
        try:
            import pytesseract
        except Exception as exc:
            raise RuntimeError(f"OCR unavailable: {exc}")
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        results: list[dict[str, Any]] = []
        width, height = image.size
        for i, text in enumerate(data.get("text", [])):
            if not text:
                continue
            bbox = (int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i]))
            results.append({"text": text, "bbox": normalize_bbox(bbox, width, height)})
        return results


class IngestNormalizer:
    def normalize(self, text: str, bbox: dict[str, float] | None, source: dict[str, Any]) -> Span:
        return build_span(text, bbox, source)


def create_ocr_engine(plugin_id: str) -> OcrEngine:
    return OcrEngine()
