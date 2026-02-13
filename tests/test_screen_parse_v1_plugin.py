from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.screen_parse_v1.plugin import ScreenParsePlugin


class _Extractor:
    def extract(self, _image_bytes: bytes) -> dict:
        return {
            "backend": "test_extractor",
            "source_provider_id": "builtin.test.extractor",
            "layout": {
                "elements": [
                    {
                        "type": "window",
                        "text": "Outlook",
                        "bbox": [100, 200, 900, 900],
                        "children": [
                            {"type": "button", "text": "Reply", "bbox": [120, 240, 220, 280]},
                        ],
                    },
                    {
                        "type": "window",
                        "text": "Slack",
                        "bbox": [1000, 100, 1800, 700],
                        "children": [],
                    },
                ]
            },
        }


def _ctx() -> PluginContext:
    extractor = _Extractor()

    def _get_cap(name: str):
        if name == "vision.extractor":
            return extractor
        return None

    return PluginContext(config={}, get_capability=_get_cap, logger=lambda _m: None)


def test_screen_parse_builds_deterministic_graph() -> None:
    plugin = ScreenParsePlugin("builtin.screen.parse.v1", _ctx())
    one = plugin.parse(b"image-bytes", frame_id="frame_1")
    two = plugin.parse(b"image-bytes", frame_id="frame_1")
    assert one == two
    assert one["schema_version"] == 1
    assert one["frame_id"] == "frame_1"
    assert one["source_backend"] == "test_extractor"
    assert len(one["nodes"]) == 3
    assert any(edge["relation"] == "contains" for edge in one["edges"])
    assert one["root_nodes"]
