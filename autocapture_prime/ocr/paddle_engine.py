from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from .base import OcrSpan
from .cache import cache_key, load_cache, save_cache
from .tesseract_engine import TesseractOcrEngine


class PaddleOcrEngine:
    """PaddleOCR-first engine with deterministic cache and local fallback."""

    def __init__(self, cache_dir: Path, config: dict[str, object] | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.config = config or {}

    def _frame_hash(self, image: Image.Image) -> str:
        data = image.tobytes()
        return hashlib.sha256(data).hexdigest()

    def _config_hash(self) -> str:
        raw = json.dumps(self.config, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def run(self, image: Image.Image, rois: list[tuple[int, int, int, int]] | None = None) -> list[OcrSpan]:
        frame_sha = self._frame_hash(image)
        cfg_sha = self._config_hash()
        result: list[OcrSpan] = []
        targets = rois or [(0, 0, image.width, image.height)]
        for roi in targets:
            key = cache_key(frame_sha, roi, cfg_sha)
            cache_path = self.cache_dir / f"{key}.json"
            cached = load_cache(cache_path)
            if cached is not None:
                result.extend(cached)
                continue
            spans = self._run_single_roi(image, roi)
            save_cache(cache_path, spans)
            result.extend(spans)
        return result

    def _run_single_roi(self, image: Image.Image, roi: tuple[int, int, int, int]) -> list[OcrSpan]:
        crop = image.crop((roi[0], roi[1], roi[2], roi[3]))
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except Exception:
            return TesseractOcrEngine().run(image, rois=[roi])
        try:
            # Deterministic defaults with angle cls off for speed.
            ocr = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
            raw = ocr.ocr(crop, cls=False)
        except Exception:
            return TesseractOcrEngine().run(image, rois=[roi])

        spans: list[OcrSpan] = []
        order = 0
        for lines in raw or []:
            for row in lines or []:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                box = row[0]
                text_info = row[1]
                if not (isinstance(box, (list, tuple)) and len(box) == 4):
                    continue
                if not (isinstance(text_info, (list, tuple)) and len(text_info) >= 2):
                    continue
                text = str(text_info[0] or "").strip()
                if not text:
                    continue
                conf = float(text_info[1] or 0.0)
                xs = [int(point[0]) for point in box]
                ys = [int(point[1]) for point in box]
                x0, y0, x1, y1 = min(xs) + roi[0], min(ys) + roi[1], max(xs) + roi[0], max(ys) + roi[1]
                spans.append(
                    OcrSpan(
                        text=text,
                        confidence=max(0.0, min(1.0, conf)),
                        bbox=(x0, y0, x1, y1),
                        reading_order=order,
                        language="en",
                    )
                )
                order += 1
        return spans
