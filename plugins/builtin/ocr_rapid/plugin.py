"""RapidOCR (ONNX) plugin."""

from __future__ import annotations

import io
import inspect
import os
from typing import Any

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class RapidOcrPlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models", {}), dict) else {}
        rapid_cfg = models_cfg.get("rapidocr", {}) if isinstance(models_cfg.get("rapidocr", {}), dict) else {}
        if not rapid_cfg:
            providers_cfg = models_cfg.get("providers", {}) if isinstance(models_cfg.get("providers", {}), dict) else {}
            rapid_cfg = providers_cfg.get("rapidocr", {}) if isinstance(providers_cfg.get("rapidocr", {}), dict) else {}
            if not rapid_cfg:
                rapid_cfg = (
                    providers_cfg.get("ocr.rapid", {})
                    if isinstance(providers_cfg.get("ocr.rapid", {}), dict)
                    else {}
                )
        self._det_model_path = rapid_cfg.get("det_model_path") or rapid_cfg.get("det_path")
        self._rec_model_path = rapid_cfg.get("rec_model_path") or rapid_cfg.get("rec_path")
        self._cls_model_path = rapid_cfg.get("cls_model_path") or rapid_cfg.get("cls_path")
        self._rec_keys_path = rapid_cfg.get("rec_keys_path") or rapid_cfg.get("keys_path")
        self._use_cuda = rapid_cfg.get("use_cuda")
        self._det_use_cuda = rapid_cfg.get("det_use_cuda")
        self._rec_use_cuda = rapid_cfg.get("rec_use_cuda")
        self._cls_use_cuda = rapid_cfg.get("cls_use_cuda")
        # Resource safety defaults (WSL-friendly). These can be overridden via config:
        # models.rapidocr.max_image_side, models.rapidocr.max_threads.
        self._max_image_side = int(rapid_cfg.get("max_image_side") or rapid_cfg.get("max_side_len") or 1600)
        self._max_threads = int(rapid_cfg.get("max_threads") or 1)
        self._engine = None
        self._init_error: str | None = None

    def capabilities(self) -> dict[str, Any]:
        return {"ocr.engine": self}

    def _limit_threads(self) -> None:
        # Best-effort: cap native thread pools for OpenMP/BLAS/ORT. This is critical
        # on WSL where default thread fanout can exceed CPU/RAM budgets.
        n = max(1, int(self._max_threads))
        env_defaults = {
            "OMP_NUM_THREADS": str(n),
            "OPENBLAS_NUM_THREADS": str(n),
            "MKL_NUM_THREADS": str(n),
            "NUMEXPR_NUM_THREADS": str(n),
            "VECLIB_MAXIMUM_THREADS": str(n),
            "OMP_WAIT_POLICY": "PASSIVE",
        }
        for k, v in env_defaults.items():
            os.environ.setdefault(k, v)
        try:
            import cv2  # type: ignore

            cv2.setNumThreads(n)
        except Exception:
            pass

    def _ensure_engine(self) -> None:
        if self._engine is not None or self._init_error is not None:
            return
        self._init_engine()

    def _init_engine(self) -> None:
        self._limit_threads()
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency guard
            self._init_error = f"rapidocr_missing:{exc}"
            return
        kwargs: dict[str, Any] = {}
        # Force onnxruntime thread pools to respect our WSL-friendly cap. RapidOCR
        # supports these keys via its config.yaml UpdateParameters.
        n = max(1, int(self._max_threads))
        kwargs["intra_op_num_threads"] = n
        kwargs["inter_op_num_threads"] = n
        if self._det_model_path:
            kwargs["det_model_path"] = str(self._det_model_path)
        if self._rec_model_path:
            kwargs["rec_model_path"] = str(self._rec_model_path)
        if self._cls_model_path:
            kwargs["cls_model_path"] = str(self._cls_model_path)
        if self._rec_keys_path:
            kwargs["rec_keys_path"] = str(self._rec_keys_path)
        if self._use_cuda is not None:
            kwargs["det_use_cuda"] = bool(self._use_cuda) if self._det_use_cuda is None else bool(self._det_use_cuda)
            kwargs["rec_use_cuda"] = bool(self._use_cuda) if self._rec_use_cuda is None else bool(self._rec_use_cuda)
            kwargs["cls_use_cuda"] = bool(self._use_cuda) if self._cls_use_cuda is None else bool(self._cls_use_cuda)
        else:
            if self._det_use_cuda is not None:
                kwargs["det_use_cuda"] = bool(self._det_use_cuda)
            if self._rec_use_cuda is not None:
                kwargs["rec_use_cuda"] = bool(self._rec_use_cuda)
            if self._cls_use_cuda is not None:
                kwargs["cls_use_cuda"] = bool(self._cls_use_cuda)
        try:
            sig = inspect.signature(RapidOCR)
            # RapidOCR declares `**kwargs`, so accepted keys are not visible via
            # inspect.signature; do not filter in that case.
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if not has_var_kw:
                allowed = set(sig.parameters.keys())
                kwargs = {k: v for k, v in kwargs.items() if k in allowed}
        except Exception:
            pass
        try:
            self._engine = RapidOCR(**kwargs)
        except Exception as exc:  # pragma: no cover - runtime error path
            self._init_error = f"rapidocr_init_failed:{exc}"
            self._engine = None

    def extract_tokens(self, image_bytes: bytes) -> list[dict[str, Any]]:
        if not image_bytes or not _PIL_AVAILABLE:
            return []
        self._ensure_engine()
        if self._engine is None:
            return []
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:
            return []
        orig_w, orig_h = image.size
        scale = 1.0
        max_side = max(1, int(self._max_image_side))
        if max_side > 0:
            longest = max(orig_w, orig_h)
            if longest > max_side:
                scale = max_side / float(longest)
                new_w = max(1, int(round(orig_w * scale)))
                new_h = max(1, int(round(orig_h * scale)))
                try:
                    image = image.resize((new_w, new_h), resample=getattr(Image, "BILINEAR", 2))
                except Exception:
                    pass
        try:
            import numpy as np  # type: ignore
        except Exception:
            return []
        arr = np.array(image)
        try:
            result = self._engine(arr)
        except Exception:
            return []
        items = result[0] if isinstance(result, tuple) else result
        tokens: list[dict[str, Any]] = []
        inv_scale = 1.0 / scale if scale and scale > 0 else 1.0
        for item in items or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            bbox = item[0]
            text = item[1]
            score = item[2] if len(item) > 2 else 0.0
            x0, y0, x1, y1 = _bbox_from_item(bbox)
            if inv_scale != 1.0:
                x0 = int(round(x0 * inv_scale))
                y0 = int(round(y0 * inv_scale))
                x1 = int(round(x1 * inv_scale))
                y1 = int(round(y1 * inv_scale))
                x0 = max(0, min(x0, orig_w))
                x1 = max(0, min(x1, orig_w))
                y0 = max(0, min(y0, orig_h))
                y1 = max(0, min(y1, orig_h))
            tokens.append(
                {
                    "text": str(text or ""),
                    "bbox": [x0, y0, x1, y1],
                    "confidence": float(score or 0.0),
                }
            )
        return tokens

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        tokens = self.extract_tokens(image_bytes)
        text = " ".join([t.get("text", "") for t in tokens if t.get("text")])
        return {"text": text, "tokens": tokens, "error": self._init_error}


def _bbox_from_item(bbox: Any) -> tuple[int, int, int, int]:
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox):
        x0, y0, x1, y1 = bbox
        return int(x0), int(y0), int(x1), int(y1)
    points: list[tuple[float, float]] = []
    if isinstance(bbox, (list, tuple)):
        for pt in bbox:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                points.append((float(pt[0]), float(pt[1])))
    if not points:
        return (0, 0, 0, 0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def create_plugin(plugin_id: str, context: PluginContext) -> RapidOcrPlugin:
    return RapidOcrPlugin(plugin_id, context)
