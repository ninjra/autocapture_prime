import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.processing_sst_vlm_ui.plugin import VLMUIStageHook


class _VLM:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def extract(self, _frame_bytes: bytes):
        return {"text": self._payload}


class SSTVLMUIHookTests(unittest.TestCase):
    def test_ui_parse_hook_builds_graph(self) -> None:
        payload = {
            "elements": [
                {
                    "type": "button",
                    "bbox": [0, 0, 40, 20],
                    "text": "OK",
                    "interactable": True,
                    "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
                    "children": [
                        {"type": "icon", "bbox": [2, 2, 10, 10], "text": "", "interactable": False},
                    ],
                }
            ]
        }
        config = {"processing": {"sst": {"ui_vlm": {"enabled": True, "max_providers": 1}}}}
        def get_capability(name: str):
            if name == "vision.extractor":
                return _VLM(json_dumps(payload))
            raise KeyError(name)

        ctx = PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None)
        hook = VLMUIStageHook("ui_vlm", ctx)
        tokens = [{"token_id": "tok1", "bbox": (5, 5, 15, 15)}]
        result = hook.run_stage(
            "ui.parse",
            {
                "frame_bytes": b"img",
                "frame_bbox": (0, 0, 100, 100),
                "tokens": tokens,
            },
        )
        self.assertIsNotNone(result)
        graph = result["element_graph"]
        self.assertIn("elements", graph)
        self.assertTrue(graph["elements"])
        self.assertTrue(graph["edges"])


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


if __name__ == "__main__":
    unittest.main()
