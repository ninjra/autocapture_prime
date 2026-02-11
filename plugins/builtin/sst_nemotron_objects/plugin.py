"""SST stage hook: Nemotron OCR/object detection (placeholder).

This plugin appends extra docs describing detected UI objects. The actual
Nemotron model integration is optional; when dependencies are missing it emits
diagnostics but does not fail the SST pipeline.
"""

from __future__ import annotations

import json
from typing import Any

from autocapture_nx.processing.sst.plugin_base import PluginInput, PluginMeta, PluginOutput, RunContext
from autocapture_nx.processing.sst.stage_plugins import SSTStagePluginBase


class NemotronObjectsPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="vision.objects.nemotron", version="0.1.0")
    stage_names = ("vision.vlm",)
    provides = ("extra_docs",)
    requires = ("frame_bytes", "frame_width", "frame_height")

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = dict(inp.items)
        diagnostics: list[dict[str, Any]] = []
        metrics: dict[str, float] = {}

        # Optional heavy deps. We fail closed (no outputs) if missing.
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForObjectDetection, AutoProcessor  # noqa: F401

            has_deps = True
        except Exception:
            has_deps = False

        if not has_deps:
            diagnostics.append({"kind": "nemotron.objects.deps_missing", "plugin": self.meta.id})
            return PluginOutput(items={"extra_docs": items.get("extra_docs", [])}, metrics=metrics, diagnostics=diagnostics)

        # TODO: Real Nemotron object detection integration.
        # For now, emit a deterministic placeholder doc to validate the fan-out
        # path and downstream persistence/indexing without requiring model files.
        extra_docs = items.get("extra_docs", [])
        if not isinstance(extra_docs, list):
            extra_docs = []
        payload = {
            "objects": [],
            "notice": "nemotron_object_detection_not_yet_configured",
        }
        extra_docs.append(
            {
                "text": json.dumps(payload, sort_keys=True),
                "doc_kind": "vision.objects.nemotron",
                "provider_id": self.plugin_id,
                "stage": "vision.vlm",
                "confidence_bp": 1000,
            }
        )
        metrics["nemotron_objects_docs"] = 1.0
        return PluginOutput(items={"extra_docs": extra_docs}, metrics=metrics, diagnostics=diagnostics)


def create_plugin(plugin_id: str, context):  # noqa: ANN001
    return NemotronObjectsPlugin(plugin_id, context)

