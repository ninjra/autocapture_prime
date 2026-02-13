import unittest

from autocapture_nx.processing.sst import pipeline as sst_pipeline


class SSTPipelineMergeSemanticsTests(unittest.TestCase):
    def test_ui_parse_replaces_element_graph_atomically(self) -> None:
        base = {
            "element_graph": {
                "state_id": "pending",
                "elements": [],
                "edges": [],
            }
        }
        update = {
            "element_graph": {
                "state_id": "vlm",
                "source_backend": "openai_compat_layout",
                "elements": [{"element_id": "root"}],
                "edges": [],
            }
        }
        diagnostics: list[dict] = []
        sst_pipeline._merge_payload(  # type: ignore[attr-defined]
            base,
            update,
            provider_id="builtin.processing.sst.ui_vlm",
            stage="ui.parse",
            diagnostics=diagnostics,
        )
        graph = base.get("element_graph", {})
        self.assertEqual(str(graph.get("state_id") or ""), "vlm")
        self.assertEqual(str(graph.get("source_backend") or ""), "openai_compat_layout")
        self.assertFalse(any(str(k).startswith("element_graph__") for k in base.keys()))

    def test_non_ui_parse_keeps_conflict_shadow_behavior(self) -> None:
        base = {"state_id": "pending"}
        update = {"state_id": "next"}
        diagnostics: list[dict] = []
        sst_pipeline._merge_payload(  # type: ignore[attr-defined]
            base,
            update,
            provider_id="builtin.example.plugin",
            stage="build.state",
            diagnostics=diagnostics,
        )
        self.assertEqual(base.get("state_id"), "pending")
        shadow_keys = [k for k in base.keys() if str(k).startswith("state_id__")]
        self.assertTrue(shadow_keys)
        self.assertTrue(diagnostics)


if __name__ == "__main__":
    unittest.main()

