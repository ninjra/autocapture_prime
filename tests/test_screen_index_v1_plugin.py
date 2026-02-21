from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.screen_index_v1.plugin import ScreenIndexPlugin


class _Embedder:
    def embed(self, text: str) -> list[float]:
        return [float(len(text or ""))]


def _ctx() -> PluginContext:
    embedder = _Embedder()

    def _get_cap(name: str):
        if name == "embedder.text":
            return embedder
        return None

    return PluginContext(config={}, get_capability=_get_cap, logger=lambda _m: None)


def test_screen_index_produces_evidence_objects() -> None:
    plugin = ScreenIndexPlugin("builtin.screen.index.v1", _ctx())
    ui_graph = {
        "schema_version": 1,
        "frame_id": "frame_1",
        "nodes": [
            {"node_id": "n1", "kind": "window", "text": "Inbox", "bbox": [10, 10, 500, 500]},
            {"node_id": "n2", "kind": "button", "text": "Reply", "bbox": [20, 40, 80, 80]},
        ],
    }
    out = plugin.index(ui_graph)
    assert out["schema_version"] == 1
    assert out["frame_id"] == "frame_1"
    assert len(out["chunks"]) == 2
    assert len(out["evidence"]) == 2
    first_ev = out["evidence"][0]
    assert first_ev["type"] == "ui_node"
    assert len(first_ev["hash"]) == 64
    assert first_ev["source"]["frame_id"] == "frame_1"
    assert out["chunks"][0]["embedding"]
