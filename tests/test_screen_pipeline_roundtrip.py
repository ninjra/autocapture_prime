from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.screen_answer_v1.plugin import ScreenAnswerPlugin
from plugins.builtin.screen_index_v1.plugin import ScreenIndexPlugin
from plugins.builtin.screen_parse_v1.plugin import ScreenParsePlugin


class _Extractor:
    def extract(self, _image_bytes: bytes) -> dict:
        return {
            "backend": "test",
            "layout": {
                "elements": [
                    {
                        "type": "window",
                        "text": "Task Set Up Open Invoice for Contractor Ricardo Lopez",
                        "bbox": [10, 10, 1000, 500],
                        "children": [],
                    }
                ]
            },
        }


class _Embedder:
    def embed(self, text: str) -> list[float]:
        return [float(len(text or ""))]


def test_screen_pipeline_roundtrip() -> None:
    extractor = _Extractor()
    embedder = _Embedder()

    def _get_cap_parse(name: str):
        if name == "vision.extractor":
            return extractor
        return None

    def _get_cap_index(name: str):
        if name == "embedder.text":
            return embedder
        return None

    parse_ctx = PluginContext(config={}, get_capability=_get_cap_parse, logger=lambda _m: None)
    index_ctx = PluginContext(config={}, get_capability=_get_cap_index, logger=lambda _m: None)
    answer_ctx = PluginContext(config={}, get_capability=lambda _n: None, logger=lambda _m: None)

    parse_plugin = ScreenParsePlugin("builtin.screen.parse.v1", parse_ctx)
    index_plugin = ScreenIndexPlugin("builtin.screen.index.v1", index_ctx)
    answer_plugin = ScreenAnswerPlugin("builtin.screen.answer.v1", answer_ctx)

    graph = parse_plugin.parse(b"fake", frame_id="frame_1")
    indexed = index_plugin.index(graph)
    answer = answer_plugin.answer("who is the contractor on the open invoice", indexed)

    assert answer["state"] == "ok"
    assert answer["claims"]
    assert "Ricardo Lopez" in answer["claims"][0]["text"]
    assert answer["claims"][0]["citations"][0]["evidence_id"].startswith("evidence_")
