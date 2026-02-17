import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.processing.sst import stage_plugins as sp


class _VLMProvider:
    def __init__(self, *, backend: str) -> None:
        self._backend = backend

    def extract(self, _frame_bytes: bytes):
        return {
            "backend": self._backend,
            "layout": {"elements": [{"type": "button", "bbox": [0, 0, 40, 20], "text": "OK"}]},
        }


class _VLMUnavailable:
    def extract(self, _frame_bytes: bytes):
        return {"backend": "unavailable", "layout": {"elements": []}}


class _VLMProviderStructured:
    def extract(self, _frame_bytes: bytes):
        return {
            "backend": "openai_compat_two_pass",
            "layout": {
                "elements": [{"type": "pane", "bbox": [0, 0, 100, 80], "text": "Inbox"}],
                "windows": [{"window_id": "w1", "app": "Outlook", "context": "vdi", "bbox": [0, 0, 100, 80]}],
                "facts": [{"key": "adv.incident.subject", "value": "Task Set Up Open Invoice", "confidence_bp": 9900}],
            },
        }


class SSTStagePluginsVLMUiParseTests(unittest.TestCase):
    def test_state_id_from_backend(self) -> None:
        self.assertEqual(sp._state_id_from_vlm_backend("heuristic"), "vlm_heuristic")
        self.assertEqual(sp._state_id_from_vlm_backend("toy.vlm"), "vlm_heuristic")
        self.assertEqual(sp._state_id_from_vlm_backend("openai_compat_layout"), "vlm")

    def test_parse_element_graph_keeps_state_id(self) -> None:
        graph = sp._parse_element_graph(
            {"elements": [{"type": "button", "bbox": [0, 0, 40, 20], "text": "OK"}]},
            tokens=[{"token_id": "tok1", "bbox": (5, 5, 10, 10)}],
            frame_bbox=(0, 0, 100, 100),
            provider_id="test.provider",
            state_id="vlm_heuristic",
        )
        self.assertIsNotNone(graph)
        self.assertEqual(graph.get("state_id"), "vlm_heuristic")
        self.assertTrue(graph.get("elements"))

    def test_parse_element_graph_preserves_ui_state_payload(self) -> None:
        graph = sp._parse_element_graph(
            {
                "elements": [{"type": "pane", "bbox": [0, 0, 100, 80], "text": "Inbox"}],
                "source_backend": "openai_compat_two_pass",
                "windows": [{"window_id": "w1", "app": "Outlook", "context": "vdi", "bbox": [0, 0, 100, 80]}],
                "facts": [{"key": "adv.incident.subject", "value": "Task Set Up Open Invoice", "confidence": 0.99}],
            },
            tokens=[{"token_id": "tok1", "bbox": (1, 1, 3, 3)}],
            frame_bbox=(0, 0, 100, 100),
            provider_id="builtin.vlm.vllm_localhost",
            state_id="vlm",
        )
        self.assertIsNotNone(graph)
        self.assertEqual(str(graph.get("source_backend") or ""), "openai_compat_two_pass")
        ui_state = graph.get("ui_state", {})
        self.assertIsInstance(ui_state, dict)
        self.assertTrue(isinstance(ui_state.get("windows"), list) and len(ui_state.get("windows", [])) >= 1)
        self.assertTrue(isinstance(ui_state.get("facts"), list) and len(ui_state.get("facts", [])) >= 1)

    def test_parse_element_graph_from_vlm_prefers_non_heuristic_provider(self) -> None:
        cap = {
            "builtin.vlm.basic": _VLMProvider(backend="heuristic"),
            "builtin.vlm.vllm_localhost": _VLMProvider(backend="openai_compat_layout"),
        }
        graph = sp._parse_element_graph_from_vlm(
            cap,
            b"img",
            tokens=[{"token_id": "tok1", "bbox": (5, 5, 10, 10)}],
            frame_bbox=(0, 0, 100, 100),
            max_providers=1,
            use_cached_tokens=False,
            prefer_live_vlm=True,
            diagnostics=[],
        )
        self.assertIsNotNone(graph)
        self.assertEqual(str(graph.get("source_provider_id") or ""), "builtin.vlm.vllm_localhost")
        self.assertEqual(str(graph.get("state_id") or ""), "vlm")

    def test_parse_element_graph_from_vlm_skips_unavailable_backend(self) -> None:
        cap = {
            "builtin.vlm.vllm_localhost": _VLMUnavailable(),
            "builtin.vlm.qwen2_vl_2b": _VLMProvider(backend="openai_compat_layout"),
        }
        diagnostics: list[dict[str, object]] = []
        graph = sp._parse_element_graph_from_vlm(
            cap,
            b"img",
            tokens=[{"token_id": "tok1", "bbox": (5, 5, 10, 10)}],
            frame_bbox=(0, 0, 100, 100),
            max_providers=1,
            use_cached_tokens=False,
            prefer_live_vlm=True,
            diagnostics=diagnostics,
        )
        self.assertIsNotNone(graph)
        self.assertEqual(str(graph.get("source_provider_id") or ""), "builtin.vlm.qwen2_vl_2b")
        kinds = {str(item.get("kind") or "") for item in diagnostics if isinstance(item, dict)}
        self.assertIn("sst.ui_vlm_backend_unavailable", kinds)

    def test_ui_parse_plugin_preserves_existing_vlm_graph(self) -> None:
        cfg = {
            "processing": {
                "sst": {
                    "ui_parse": {
                        "enabled": True,
                        "mode": "detector",
                        "fallback_detector": True,
                        "max_providers": 1,
                    }
                }
            }
        }

        def _cap(_name: str):
            raise KeyError("no capability")

        ctx = PluginContext(config=cfg, get_capability=_cap, logger=lambda _m: None)
        plugin = sp.UiParsePlugin("builtin.sst.ui.parse", ctx)
        existing = {
            "state_id": "vlm",
            "source_backend": "openai_compat_layout",
            "elements": (
                {
                    "element_id": "root",
                    "type": "window",
                    "bbox": (0, 0, 100, 100),
                    "text_refs": (),
                    "label": None,
                    "interactable": False,
                    "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
                    "parent_id": None,
                    "children_ids": (),
                    "z": 0,
                    "app_hint": None,
                },
            ),
            "edges": tuple(),
        }
        result = plugin.run_stage(
            "ui.parse",
            {
                "frame_bbox": (0, 0, 100, 100),
                "tokens": [{"token_id": "tok1", "bbox": (1, 1, 3, 3), "text": "ok"}],
                "element_graph": existing,
            },
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["element_graph"]["state_id"], "vlm")
        self.assertEqual(result["element_graph"]["source_backend"], "openai_compat_layout")

    def test_ui_parse_plugin_replaces_weak_existing_vlm_graph(self) -> None:
        cfg = {
            "processing": {
                "sst": {
                    "ui_parse": {
                        "enabled": True,
                        "mode": "vlm_json",
                        "fallback_detector": False,
                        "max_providers": 1,
                    }
                }
            }
        }

        def _cap(name: str):
            if name == "vision.extractor":
                return {"builtin.vlm.vllm_localhost": _VLMProviderStructured()}
            raise KeyError(name)

        ctx = PluginContext(config=cfg, get_capability=_cap, logger=lambda _m: None)
        plugin = sp.UiParsePlugin("builtin.sst.ui.parse", ctx)
        weak_existing = {
            "state_id": "vlm",
            "source_backend": "cached_vlm_token",
            "elements": (
                {
                    "element_id": "root",
                    "type": "window",
                    "bbox": (0, 0, 100, 100),
                    "text_refs": (),
                    "label": None,
                    "interactable": False,
                    "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
                    "parent_id": None,
                    "children_ids": (),
                    "z": 0,
                    "app_hint": None,
                },
            ),
            "edges": tuple(),
        }
        result = plugin.run_stage(
            "ui.parse",
            {
                "frame_bytes": b"img",
                "frame_bbox": (0, 0, 100, 100),
                "tokens": [{"token_id": "tok1", "bbox": (1, 1, 3, 3), "text": "ok"}],
                "element_graph": weak_existing,
            },
        )
        self.assertIsNotNone(result)
        graph = result["element_graph"]
        self.assertEqual(str(graph.get("source_backend") or ""), "openai_compat_two_pass")
        ui_state = graph.get("ui_state", {})
        self.assertTrue(isinstance(ui_state.get("facts"), list) and len(ui_state.get("facts", [])) >= 1)

    def test_coerce_bbox_accepts_normalized(self) -> None:
        bbox = sp._coerce_bbox([0.1, 0.2, 0.6, 0.7], (0, 0, 1000, 500))
        self.assertEqual(bbox, (100, 100, 600, 350))

    def test_recover_layout_from_partial_json_accepts_single_element(self) -> None:
        partial = '{"elements":[{"type":"window","bbox":[0,0,100,100],"text":"Inbox","children":[{"type":"button"'
        recovered = sp._recover_layout_from_partial_json(partial, (0, 0, 100, 100))
        self.assertIsInstance(recovered, dict)
        self.assertGreaterEqual(len(recovered.get("elements", [])), 1)

    def test_parse_element_graph_from_vlm_uses_cached_tokens_as_fallback(self) -> None:
        cap = {"builtin.vlm.vllm_localhost": _VLMUnavailable()}
        cached_layout = json_dumps({"elements": [{"type": "window", "bbox": [0, 0, 100, 100], "text": "Inbox"}]})
        diagnostics: list[dict[str, object]] = []
        graph = sp._parse_element_graph_from_vlm(
            cap,
            b"img",
            tokens=[
                {
                    "token_id": "tok-vlm",
                    "source": "vlm",
                    "provider_id": "builtin.vlm.vllm_localhost",
                    "text": cached_layout,
                    "bbox": (0, 0, 100, 100),
                }
            ],
            frame_bbox=(0, 0, 100, 100),
            max_providers=1,
            use_cached_tokens=True,
            prefer_live_vlm=True,
            diagnostics=diagnostics,
        )
        self.assertIsNotNone(graph)
        self.assertEqual(str(graph.get("source_backend") or ""), "cached_vlm_token")
        kinds = {str(item.get("kind") or "") for item in diagnostics if isinstance(item, dict)}
        self.assertIn("sst.ui_vlm_used_cached_tokens_fallback", kinds)

    def test_parse_element_graph_from_cached_tokens_infers_two_pass_backend(self) -> None:
        cap = {"builtin.vlm.vllm_localhost": _VLMUnavailable()}
        cached_layout = json_dumps(
            {
                "elements": [{"type": "window", "bbox": [0, 0, 100, 100], "text": "Inbox"}],
                "facts": [{"key": "adv.window.count", "value": "4", "confidence": 0.95}],
                "windows": [{"window_id": "w1", "app": "Outlook", "context": "vdi", "bbox": [0, 0, 100, 100]}],
            }
        )
        diagnostics: list[dict[str, object]] = []
        graph = sp._parse_element_graph_from_vlm(
            cap,
            b"img",
            tokens=[
                {
                    "token_id": "tok-vlm",
                    "source": "vlm",
                    "provider_id": "builtin.vlm.vllm_localhost",
                    "text": cached_layout,
                    "bbox": (0, 0, 100, 100),
                }
            ],
            frame_bbox=(0, 0, 100, 100),
            max_providers=1,
            use_cached_tokens=True,
            prefer_live_vlm=True,
            diagnostics=diagnostics,
        )
        self.assertIsNotNone(graph)
        self.assertEqual(str(graph.get("source_backend") or ""), "openai_compat_two_pass_inferred")


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


if __name__ == "__main__":
    unittest.main()
