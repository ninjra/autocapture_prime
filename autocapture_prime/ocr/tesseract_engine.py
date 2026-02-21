from __future__ import annotations

from typing import Any

from PIL import Image

from .base import OcrSpan


class TesseractOcrEngine:
    def run(self, image: Image.Image, rois: list[tuple[int, int, int, int]] | None = None) -> list[OcrSpan]:
        try:
            import pytesseract  # type: ignore
        except Exception:
            return []
        boxes: list[OcrSpan] = []
        targets = rois or [(0, 0, image.width, image.height)]
        idx = 0
        for roi in targets:
            crop = image.crop((roi[0], roi[1], roi[2], roi[3]))
            data: dict[str, Any] = pytesseract.image_to_data(crop, output_type=pytesseract.Output.DICT)
            length = len(data.get("text", []))
            for i in range(length):
                text = str(data["text"][i] or "").strip()
                if not text:
                    continue
                conf = data.get("conf", [0])[i]
                x = int(data.get("left", [0])[i]) + roi[0]
                y = int(data.get("top", [0])[i]) + roi[1]
                w = int(data.get("width", [0])[i])
                h = int(data.get("height", [0])[i])
                boxes.append(
                    OcrSpan(
                        text=text,
                        confidence=max(0.0, min(1.0, float(conf) / 100.0)),
                        bbox=(x, y, x + w, y + h),
                        reading_order=idx,
                    )
                )
                idx += 1
        return boxes
