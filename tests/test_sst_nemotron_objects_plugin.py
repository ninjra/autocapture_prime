import json
import unittest
from typing import Any

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.sst_nemotron_objects.plugin import NemotronObjectsPlugin


class _Provider:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def extract(self, _frame_bytes: bytes) -> dict[str, Any]:
        return dict(self._payload)


def _ctx(provider_payload: dict[str, Any] | None):
    def _get_capability(name: str):
        if name != "vision.extractor":
            return None
        if provider_payload is None:
            return None
        return {"provider.main": _Provider(provider_payload)}

    return PluginContext(
        config={},
        get_capability=_get_capability,
        logger=lambda _msg: None,
    )


class NemotronObjectsPluginTests(unittest.TestCase):
    def test_emits_object_doc_from_layout(self) -> None:
        payload = {
            "backend": "openai_compat_two_pass",
            "layout": {
                "elements": [
                    {"type": "window", "bbox": [0, 0, 1000, 600], "label": "Main"},
                    {
                        "type": "button",
                        "bbox": [100, 120, 260, 170],
                        "text": "COMPLETE",
                        "interactable": True,
                        "state": {"focused": True},
                    },
                ],
                "ui_state": {
                    "windows": [
                        {
                            "label": "Outlook",
                            "app": "Outlook",
                            "context": "vdi",
                            "bbox": [0, 0, 1000, 600],
                            "visibility": "fully_visible",
                        }
                    ]
                },
            },
        }
        plugin = NemotronObjectsPlugin("builtin.sst.nemotron_objects", _ctx(payload))
        out = plugin.run_stage(
            "vision.vlm",
            {
                "run_id": "run",
                "ts_ms": 1,
                "frame_bytes": b"frame",
                "frame_width": 1000,
                "frame_height": 600,
                "extra_docs": [],
            },
        )
        self.assertIsInstance(out, dict)
        docs = out.get("extra_docs", []) if isinstance(out, dict) else []
        self.assertEqual(len(docs), 1)
        text = str(docs[0].get("text") or "")
        parsed = json.loads(text)
        self.assertEqual(parsed.get("schema_version"), 1)
        self.assertEqual(parsed.get("backend"), "openai_compat_two_pass")
        self.assertGreaterEqual(len(parsed.get("objects", [])), 1)
        self.assertEqual(parsed.get("windows", [])[0].get("context"), "vdi")
        metrics = out.get("metrics", {})
        self.assertEqual(float(metrics.get("nemotron_objects_docs", 0.0)), 1.0)

    def test_emits_unavailable_diagnostic_when_provider_absent(self) -> None:
        plugin = NemotronObjectsPlugin("builtin.sst.nemotron_objects", _ctx(None))
        out = plugin.run_stage(
            "vision.vlm",
            {
                "run_id": "run",
                "ts_ms": 1,
                "frame_bytes": b"frame",
                "frame_width": 1000,
                "frame_height": 600,
                "extra_docs": [],
            },
        )
        self.assertIsInstance(out, dict)
        docs = out.get("extra_docs", []) if isinstance(out, dict) else []
        self.assertEqual(docs, [])
        diagnostics = out.get("diagnostics", []) if isinstance(out, dict) else []
        kinds = {str(item.get("kind")) for item in diagnostics if isinstance(item, dict)}
        self.assertIn("nemotron.objects.unavailable", kinds)


if __name__ == "__main__":
    unittest.main()
