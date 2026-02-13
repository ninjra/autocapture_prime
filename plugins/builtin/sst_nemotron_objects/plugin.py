"""SST stage hook: emit structured object docs from VLM layout output."""

from __future__ import annotations

import json
from typing import Any

from autocapture_nx.kernel.providers import capability_providers
from autocapture_nx.processing.sst.plugin_base import PluginInput, PluginMeta, PluginOutput, RunContext
from autocapture_nx.processing.sst.stage_plugins import SSTStagePluginBase


class NemotronObjectsPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="vision.objects.nemotron", version="0.2.0")
    stage_names = ("vision.vlm",)
    provides = ("extra_docs",)
    requires = ("frame_bytes", "frame_width", "frame_height")

    def __init__(self, plugin_id: str, context) -> None:  # noqa: ANN001
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._max_objects = int(cfg.get("max_objects") or 256)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = dict(inp.items)
        diagnostics: list[dict[str, Any]] = []
        metrics: dict[str, float] = {}

        frame_bytes = items.get("frame_bytes")
        if not isinstance(frame_bytes, (bytes, bytearray)) or not frame_bytes:
            diagnostics.append({"kind": "nemotron.objects.missing_frame", "plugin": self.meta.id})
            return PluginOutput(items={"extra_docs": _coerce_docs(items.get("extra_docs"))}, metrics=metrics, diagnostics=diagnostics)

        providers = _sorted_providers(ctx.stores.get("vlm"))
        selected_provider = ""
        selected_backend = ""
        objects: list[dict[str, Any]] = []
        windows: list[dict[str, Any]] = []

        for provider_id, provider in providers:
            selected_provider = str(provider_id)
            try:
                response = provider.extract(bytes(frame_bytes))
            except Exception as exc:
                diagnostics.append(
                    {
                        "kind": "nemotron.objects.provider_error",
                        "plugin": self.meta.id,
                        "provider_id": selected_provider,
                        "error": type(exc).__name__,
                    }
                )
                continue
            if not isinstance(response, dict):
                continue
            selected_backend = str(response.get("backend") or "").strip()
            layout = response.get("layout") if isinstance(response.get("layout"), dict) else {}
            parsed_objects = _extract_objects(layout, max_objects=self._max_objects)
            parsed_windows = _extract_windows(layout)
            if parsed_objects or parsed_windows:
                objects = parsed_objects
                windows = parsed_windows
                break

        extra_docs = _coerce_docs(items.get("extra_docs"))
        if not objects and not windows:
            diagnostics.append({"kind": "nemotron.objects.unavailable", "plugin": self.meta.id})
            return PluginOutput(items={"extra_docs": extra_docs}, metrics=metrics, diagnostics=diagnostics)

        payload = {
            "schema_version": 1,
            "provider_id": selected_provider,
            "backend": selected_backend,
            "objects": objects,
            "windows": windows,
        }
        extra_docs.append(
            {
                "text": json.dumps(payload, sort_keys=True, separators=(",", ":")),
                "doc_kind": "vision.objects.nemotron",
                "provider_id": self.plugin_id,
                "stage": "vision.vlm",
                "confidence_bp": 7500,
            }
        )
        metrics["nemotron_objects_docs"] = 1.0
        metrics["nemotron_objects_count"] = float(len(objects))
        metrics["nemotron_windows_count"] = float(len(windows))
        diagnostics.append(
            {
                "kind": "nemotron.objects.used_provider",
                "plugin": self.meta.id,
                "provider_id": selected_provider,
                "backend": selected_backend,
            }
        )
        return PluginOutput(items={"extra_docs": extra_docs}, metrics=metrics, diagnostics=diagnostics)


def create_plugin(plugin_id: str, context):  # noqa: ANN001
    return NemotronObjectsPlugin(plugin_id, context)


def _coerce_docs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _sorted_providers(capability: Any | None) -> list[tuple[str, Any]]:
    providers = capability_providers(capability, "vision.extractor")
    providers.sort(key=lambda pair: (-_provider_priority(pair[0]), str(pair[0])))
    return providers


def _provider_priority(provider_id: str) -> int:
    low = str(provider_id or "").strip().casefold()
    score = 0
    if "nemotron" in low:
        score += 80
    if "vllm" in low or "localhost" in low or "openai" in low:
        score += 60
    if "qwen" in low or "internvl" in low or "mai" in low:
        score += 30
    if "stub" in low or "toy" in low or "heuristic" in low:
        score -= 40
    return score


def _extract_objects(layout: dict[str, Any], *, max_objects: int) -> list[dict[str, Any]]:
    elements = layout.get("elements", []) if isinstance(layout, dict) else []
    if not isinstance(elements, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[int, int, int, int]]] = set()
    for item in elements:
        if not isinstance(item, dict):
            continue
        bbox = _to_bbox(item.get("bbox"))
        if bbox is None:
            continue
        el_type = str(item.get("type") or "other").strip()
        if not el_type:
            el_type = "other"
        label = str(item.get("text") or item.get("label") or "").strip()
        if not label and el_type in {"window", "root"}:
            continue
        key = (el_type, label, bbox)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "type": el_type,
                "label": label,
                "bbox": list(bbox),
                "interactable": bool(item.get("interactable", False)),
                "state": item.get("state") if isinstance(item.get("state"), dict) else {},
            }
        )
        if len(out) >= int(max(1, max_objects)):
            break
    return out


def _extract_windows(layout: dict[str, Any]) -> list[dict[str, Any]]:
    ui_state = layout.get("ui_state") if isinstance(layout, dict) else {}
    windows = ui_state.get("windows", []) if isinstance(ui_state, dict) else []
    out: list[dict[str, Any]] = []
    if not isinstance(windows, list):
        return out
    for item in windows:
        if not isinstance(item, dict):
            continue
        bbox = _to_bbox(item.get("bbox"))
        if bbox is None:
            continue
        out.append(
            {
                "label": str(item.get("label") or "").strip(),
                "app": str(item.get("app") or "").strip(),
                "context": str(item.get("context") or "unknown").strip() or "unknown",
                "bbox": list(bbox),
                "visibility": str(item.get("visibility") or "unknown").strip() or "unknown",
            }
        )
    return out


def _to_bbox(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1 = int(round(float(value[0])))
        y1 = int(round(float(value[1])))
        x2 = int(round(float(value[2])))
        y2 = int(round(float(value[3])))
    except Exception:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)
