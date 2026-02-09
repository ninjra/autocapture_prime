"""Local OCR plugin with deterministic fallback and optional Tesseract support.

WSL stability note:
- `pytesseract.image_to_data()` can be very slow on large frames and can hang the
  fixture pipeline. For the default `ocr.engine` surface we prefer text-only OCR
  (`image_to_string`) and let downstream stages approximate bboxes when needed.
"""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class OCRLocal(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models", {}), dict) else {}
        self._tesseract_cmd = models_cfg.get("ocr_path")
        self._lang = models_cfg.get("ocr_lang")
        self._psm = models_cfg.get("ocr_psm")
        self._oem = models_cfg.get("ocr_oem")
        # OCR must be reliable on ultra-wide screenshots; prefer tiling over heavy
        # global downscales (which drop small UI text like tray clocks/tabs).
        self._max_image_side = int(models_cfg.get("ocr_max_image_side") or 0)
        self._tile_width = int(models_cfg.get("ocr_tile_width") or 2000)
        self._tile_overlap = int(models_cfg.get("ocr_tile_overlap") or 200)

    def capabilities(self) -> dict[str, Any]:
        return {"ocr.engine": self}

    def extract_tokens(self, image_bytes: bytes) -> dict[str, Any]:
        # Intentionally return no bbox-bearing tokens. Downstream callers fall back
        # to `extract()` and approximate bboxes deterministically.
        _ = image_bytes
        return {"tokens": []}

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        if not image_bytes:
            return {"text": "", "tokens": []}
        try:
            from PIL import Image  # type: ignore
            from PIL import ImageEnhance, ImageOps  # type: ignore
        except Exception:
            return {"text": "", "tokens": []}
        try:
            import pytesseract  # type: ignore
        except Exception:
            return {"text": "", "tokens": []}
        try:
            if self._tesseract_cmd and hasattr(pytesseract, "pytesseract"):
                try:
                    pytesseract.pytesseract.tesseract_cmd = str(self._tesseract_cmd)
                except Exception:
                    pass
            img = Image.open(_as_bytes_io(image_bytes)).convert("RGB")
        except Exception:
            return {"text": "", "tokens": []}

        def _preprocess(tile):
            # Screen captures frequently contain dark UI. A modest contrast boost on
            # grayscale improves Tesseract recall without heavy per-pixel ops.
            try:
                gray = ImageOps.grayscale(tile)
                return ImageEnhance.Contrast(gray).enhance(1.8)
            except Exception:
                return tile

        config_parts: list[str] = []
        # Default to psm=6 (single uniform block of text) which performs better on
        # dense UI screenshots than Tesseract's fully automatic page segmentation.
        psm = 6 if self._psm is None else int(self._psm)
        config_parts.append(f"--psm {psm}")
        if self._oem is not None:
            config_parts.append(f"--oem {int(self._oem)}")
        config = " ".join(config_parts) if config_parts else None
        kwargs: dict[str, Any] = {}
        if self._lang:
            kwargs["lang"] = str(self._lang)
        if config:
            kwargs["config"] = config
        # Keep OCR bounded: tile very wide screenshots into vertical stripes so we
        # don't feed massive multi-monitor frames into a single Tesseract call.
        w, h = img.size
        tile_w = max(200, int(self._tile_width))
        overlap = max(0, int(self._tile_overlap))
        step = max(1, tile_w - overlap)

        def _maybe_downscale(tile):
            max_side = int(self._max_image_side or 0)
            if max_side <= 0:
                return tile
            try:
                tw, th = tile.size
                longest = max(tw, th)
                if longest <= max_side:
                    return tile
                scale = max_side / float(longest)
                nw = max(1, int(round(tw * scale)))
                nh = max(1, int(round(th * scale)))
                return tile.resize((nw, nh), resample=getattr(Image, "BILINEAR", 2))
            except Exception:
                return tile

        texts: list[str] = []
        try:
            if w <= tile_w:
                tile = _preprocess(_maybe_downscale(img))
                texts.append(str(pytesseract.image_to_string(tile, **kwargs) or ""))
            else:
                # Deterministic stripe tiling, capped to avoid pathological configs.
                stripes = 0
                x0 = 0
                while x0 < w and stripes < 12:
                    x1 = min(w, x0 + tile_w)
                    tile = img.crop((x0, 0, x1, h))
                    tile = _preprocess(_maybe_downscale(tile))
                    texts.append(str(pytesseract.image_to_string(tile, **kwargs) or ""))
                    stripes += 1
                    if x1 >= w:
                        break
                    x0 += step
        except Exception:
            texts = []

        # Tray clock is often tiny; run an extra focused OCR pass for the bottom-right.
        try:
            crop = img.crop((int(w * 0.75), int(h * 0.80), w, h))
            crop = _preprocess(_maybe_downscale(crop))
            texts.append(str(pytesseract.image_to_string(crop, **kwargs) or ""))
        except Exception:
            pass

        text = "\n".join([t.strip() for t in texts if t and str(t).strip()]).strip()
        return {"text": text, "tokens": []}


def _as_bytes_io(data: bytes):
    from io import BytesIO
    return BytesIO(data)


def create_plugin(plugin_id: str, context: PluginContext) -> OCRLocal:
    return OCRLocal(plugin_id, context)
