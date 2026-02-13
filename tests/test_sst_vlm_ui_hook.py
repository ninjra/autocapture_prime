import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.processing_sst_vlm_ui.plugin import VLMUIStageHook


class _VLM:
    def __init__(self, payload: str, *, backend: str = "", layout: dict | None = None) -> None:
        self._payload = payload
        self._backend = backend
        self._layout = layout

    def extract(self, _frame_bytes: bytes):
        out = {"text": self._payload}
        if self._backend:
            out["backend"] = self._backend
        if isinstance(self._layout, dict):
            out["layout"] = self._layout
        return out


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
                return _VLM(json_dumps(payload), backend="openai_compat_layout")
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
        self.assertEqual(graph.get("state_id"), "vlm")

    def test_ui_parse_hook_marks_heuristic_backend(self) -> None:
        payload = {"elements": [{"type": "button", "bbox": [0, 0, 40, 20], "text": "OK"}]}
        config = {"processing": {"sst": {"ui_vlm": {"enabled": True, "max_providers": 1}}}}

        def get_capability(name: str):
            if name == "vision.extractor":
                return _VLM(json_dumps(payload), backend="heuristic")
            raise KeyError(name)

        ctx = PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None)
        hook = VLMUIStageHook("ui_vlm", ctx)
        result = hook.run_stage(
            "ui.parse",
            {
                "frame_bytes": b"img",
                "frame_bbox": (0, 0, 100, 100),
                "tokens": [{"token_id": "tok1", "bbox": (5, 5, 15, 15)}],
            },
        )
        self.assertIsNone(result)

    def test_ui_parse_hook_prefers_localhost_vlm_provider(self) -> None:
        payload = {"elements": [{"type": "button", "bbox": [0, 0, 40, 20], "text": "OK"}]}
        config = {"processing": {"sst": {"ui_vlm": {"enabled": True, "max_providers": 1}}}}

        def get_capability(name: str):
            if name == "vision.extractor":
                return {
                    "builtin.vlm.basic": _VLM(json_dumps(payload), backend="heuristic"),
                    "builtin.vlm.vllm_localhost": _VLM(json_dumps(payload), backend="openai_compat_layout"),
                }
            raise KeyError(name)

        ctx = PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None)
        hook = VLMUIStageHook("ui_vlm", ctx)
        result = hook.run_stage(
            "ui.parse",
            {
                "frame_bytes": b"img",
                "frame_bbox": (0, 0, 100, 100),
                "tokens": [{"token_id": "tok1", "bbox": (5, 5, 15, 15)}],
            },
        )
        self.assertIsNotNone(result)
        graph = result["element_graph"]
        self.assertEqual(str(graph.get("source_provider_id") or ""), "builtin.vlm.vllm_localhost")
        self.assertEqual(str(graph.get("state_id") or ""), "vlm")

    def test_ui_parse_hook_accepts_layout_payload_with_label_field(self) -> None:
        layout = {
            "state_id": "vlm",
            "elements": [
                {
                    "type": "text",
                    "bbox": [0, 0, 40, 20],
                    "label": "Inbox",
                    "interactable": False,
                    "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
                    "children": [],
                }
            ],
        }
        config = {"processing": {"sst": {"ui_vlm": {"enabled": True, "max_providers": 1}}}}

        def get_capability(name: str):
            if name == "vision.extractor":
                return _VLM("{}", backend="transformers.qwen2vl_two_pass", layout=layout)
            raise KeyError(name)

        ctx = PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None)
        hook = VLMUIStageHook("ui_vlm", ctx)
        result = hook.run_stage(
            "ui.parse",
            {
                "frame_bytes": b"img",
                "frame_bbox": (0, 0, 100, 100),
                "tokens": [{"token_id": "tok1", "bbox": (5, 5, 15, 15)}],
            },
        )
        self.assertIsNotNone(result)
        graph = result["element_graph"]
        self.assertEqual(str(graph.get("state_id") or ""), "vlm")
        self.assertEqual(str(graph.get("source_backend") or ""), "transformers.qwen2vl_two_pass")
        labels = [str(el.get("label") or "") for el in graph.get("elements", []) if isinstance(el, dict)]
        self.assertIn("Inbox", labels)

    def test_ui_parse_hook_accepts_normalized_bbox_layout(self) -> None:
        layout = {
            "state_id": "vlm",
            "elements": [
                {
                    "type": "text",
                    "bbox": [0.1, 0.2, 0.5, 0.6],
                    "label": "Inbox",
                    "children": [],
                }
            ],
        }
        config = {"processing": {"sst": {"ui_vlm": {"enabled": True, "max_providers": 1}}}}

        def get_capability(name: str):
            if name == "vision.extractor":
                return _VLM("{}", backend="transformers.qwen2vl_two_pass", layout=layout)
            raise KeyError(name)

        ctx = PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None)
        hook = VLMUIStageHook("ui_vlm", ctx)
        result = hook.run_stage(
            "ui.parse",
            {
                "frame_bytes": b"img",
                "frame_bbox": (0, 0, 100, 100),
                "tokens": [{"token_id": "tok1", "bbox": (15, 25, 25, 35)}],
            },
        )
        self.assertIsNotNone(result)
        graph = result["element_graph"]
        inbox_nodes = [
            el for el in graph.get("elements", ()) if isinstance(el, dict) and str(el.get("label") or "") == "Inbox"
        ]
        self.assertTrue(inbox_nodes)
        self.assertEqual(tuple(inbox_nodes[0].get("bbox", ())), (10, 20, 50, 60))

    def test_ui_parse_hook_recovers_partial_unparsed_text(self) -> None:
        partial = '```json {"elements":[{"type":"window","bbox":[0,0,100,100],"text":"Inbox","children":[{"type":"button"'
        config = {"processing": {"sst": {"ui_vlm": {"enabled": True, "max_providers": 1}}}}

        def get_capability(name: str):
            if name == "vision.extractor":
                return _VLM(partial, backend="openai_compat_unparsed")
            raise KeyError(name)

        ctx = PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None)
        hook = VLMUIStageHook("ui_vlm", ctx)
        result = hook.run_stage(
            "ui.parse",
            {
                "frame_bytes": b"img",
                "frame_bbox": (0, 0, 100, 100),
                "tokens": [{"token_id": "tok1", "bbox": (5, 5, 15, 15)}],
            },
        )
        self.assertIsNotNone(result)
        graph = result["element_graph"]
        self.assertEqual(str(graph.get("state_id") or ""), "vlm")
        self.assertEqual(str(graph.get("source_backend") or ""), "openai_compat_text_recovered")
        self.assertGreaterEqual(len(graph.get("elements", ())), 2)

    def test_ui_parse_hook_uses_cached_vlm_tokens_before_live_extract(self) -> None:
        config = {"processing": {"sst": {"ui_vlm": {"enabled": True, "max_providers": 1}}}}

        class _AlwaysFails:
            def extract(self, _frame_bytes: bytes):
                raise RuntimeError("live extract unavailable")

        def get_capability(name: str):
            if name == "vision.extractor":
                return _AlwaysFails()
            raise KeyError(name)

        ctx = PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None)
        hook = VLMUIStageHook("ui_vlm", ctx)
        cached_layout = json_dumps(
            {"elements": [{"type": "window", "bbox": [0, 0, 100, 100], "text": "Inbox", "children": []}]}
        )
        result = hook.run_stage(
            "ui.parse",
            {
                "frame_bytes": b"img",
                "frame_bbox": (0, 0, 100, 100),
                "tokens": [
                    {
                        "token_id": "tok-vlm",
                        "source": "vlm",
                        "provider_id": "builtin.vlm.vllm_localhost",
                        "text": cached_layout,
                        "bbox": (0, 0, 100, 100),
                    }
                ],
            },
        )
        self.assertIsNotNone(result)
        graph = result["element_graph"]
        self.assertEqual(str(graph.get("state_id") or ""), "vlm")
        self.assertEqual(str(graph.get("source_backend") or ""), "cached_vlm_token")


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


if __name__ == "__main__":
    unittest.main()
