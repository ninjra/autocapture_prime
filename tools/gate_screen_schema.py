#!/usr/bin/env python3
"""Gate: validate screen.parse/index outputs against UI/provenance schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.screen_index_v1.plugin import ScreenIndexPlugin
from plugins.builtin.screen_parse_v1.plugin import ScreenParsePlugin


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonschema_validate(schema: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, str]:
    try:
        import jsonschema  # type: ignore
    except Exception:
        # Best effort fallback for minimal envs.
        required = schema.get("required", [])
        if not isinstance(required, list):
            required = []
        missing = [key for key in required if key not in payload]
        if missing:
            return False, f"missing_required:{','.join(missing)}"
        return True, "fallback_ok"
    try:
        jsonschema.validate(payload, schema)
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


def _build_samples() -> tuple[dict[str, Any], dict[str, Any]]:
    class _Extractor:
        def extract(self, _image_bytes: bytes) -> dict[str, Any]:
            return {
                "backend": "gate_screen_schema",
                "layout": {
                    "elements": [
                        {
                            "type": "window",
                            "text": "Outlook",
                            "bbox": [10, 10, 800, 700],
                            "children": [{"type": "button", "text": "Reply", "bbox": [40, 50, 120, 90]}],
                        }
                    ]
                },
            }

    class _Embedder:
        def embed(self, text: str) -> list[float]:
            return [float(len(text or ""))]

    extractor = _Extractor()
    embedder = _Embedder()

    parse_ctx = PluginContext(config={}, get_capability=lambda name: extractor if name == "vision.extractor" else None, logger=lambda _m: None)
    index_ctx = PluginContext(config={}, get_capability=lambda name: embedder if name == "embedder.text" else None, logger=lambda _m: None)

    parse_plugin = ScreenParsePlugin("builtin.screen.parse.v1", parse_ctx)
    index_plugin = ScreenIndexPlugin("builtin.screen.index.v1", index_ctx)
    ui_graph = parse_plugin.parse(b"fake", frame_id="frame_gate")
    indexed = index_plugin.index(ui_graph)
    provenance = {
        "schema_version": 1,
        "evidence": indexed.get("evidence", []) if isinstance(indexed, dict) else [],
    }
    return ui_graph, provenance


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ui_graph_schema = _load_schema(root / "docs" / "schemas" / "ui_graph.schema.json")
    provenance_schema = _load_schema(root / "docs" / "schemas" / "provenance.schema.json")
    ui_graph, provenance = _build_samples()
    ui_ok, ui_detail = _jsonschema_validate(ui_graph_schema, ui_graph)
    prov_ok, prov_detail = _jsonschema_validate(provenance_schema, provenance)

    payload = {
        "schema_version": 1,
        "ok": bool(ui_ok and prov_ok),
        "checks": [
            {"name": "ui_graph_schema", "ok": bool(ui_ok), "detail": ui_detail},
            {"name": "provenance_schema", "ok": bool(prov_ok), "detail": prov_detail},
        ],
        "samples": {
            "ui_graph_node_count": int(len(ui_graph.get("nodes", []))) if isinstance(ui_graph, dict) else 0,
            "provenance_evidence_count": int(len(provenance.get("evidence", []))) if isinstance(provenance, dict) else 0,
        },
    }
    out = root / "artifacts" / "phaseA" / "gate_screen_schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if payload["ok"]:
        print("OK: screen schema gate")
        return 0
    print("FAIL: screen schema gate")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

