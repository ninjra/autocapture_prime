import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.observation_graph.plugin import ObservationGraphPlugin


class ObservationGraphVLMGroundingTests(unittest.TestCase):
    def _plugin(self) -> ObservationGraphPlugin:
        def _cap(_name: str):
            raise KeyError("no capability")

        ctx = PluginContext(config={}, get_capability=_cap, logger=lambda _m: None)
        return ObservationGraphPlugin("builtin.observation.graph", ctx)

    def test_single_element_vlm_graph_is_vlm_grounded(self) -> None:
        plugin = self._plugin()
        payload = {
            "text_lines": [{"text": "Now playing: Master Cylinder - Jung At Heart", "bbox": [10, 10, 300, 28]}],
            "extra_docs": [],
            "tokens_raw": [],
            "frame_bytes": b"",
            "element_graph": {
                "state_id": "vlm",
                "source_backend": "openai_compat_layout",
                "source_provider_id": "builtin.vlm.vllm_localhost",
                "elements": [
                    {"label": "Now playing: Master Cylinder - Jung At Heart", "bbox": [10, 10, 300, 28]},
                ],
            },
        }
        result = plugin.run_stage("persist.bundle", payload)
        self.assertIsInstance(result, dict)
        docs = result.get("extra_docs", [])
        self.assertTrue(isinstance(docs, list) and docs)
        now_playing = [d for d in docs if isinstance(d, dict) and str(d.get("doc_kind") or "") == "obs.media.now_playing"]
        self.assertTrue(now_playing)
        meta = now_playing[0].get("meta", {}) if isinstance(now_playing[0].get("meta"), dict) else {}
        self.assertEqual(str(meta.get("source_modality") or ""), "vlm")
        self.assertTrue(bool(meta.get("vlm_grounded", False)))

    def test_root_only_vlm_graph_is_not_vlm_grounded(self) -> None:
        plugin = self._plugin()
        payload = {
            "text_lines": [{"text": "Now playing: Master Cylinder - Jung At Heart", "bbox": [10, 10, 360, 28]}],
            "extra_docs": [],
            "tokens_raw": [],
            "frame_bytes": b"",
            "element_graph": {
                "state_id": "vlm",
                "source_backend": "openai_compat_two_pass",
                "source_provider_id": "builtin.vlm.vllm_localhost",
                "elements": [
                    {"label": "", "bbox": [0, 0, 100, 100]},
                ],
            },
        }
        result = plugin.run_stage("persist.bundle", payload)
        self.assertIsInstance(result, dict)
        docs = result.get("extra_docs", [])
        media = [d for d in docs if isinstance(d, dict) and str(d.get("doc_kind") or "") == "obs.media.now_playing"]
        self.assertTrue(media)
        meta = media[0].get("meta", {}) if isinstance(media[0].get("meta"), dict) else {}
        self.assertEqual(str(meta.get("source_modality") or ""), "ocr")
        self.assertFalse(bool(meta.get("vlm_grounded", True)))

    def test_incident_card_includes_normalized_button_boxes(self) -> None:
        plugin = self._plugin()
        payload = {
            "text_lines": [],
            "extra_docs": [],
            "tokens_raw": [],
            "frame_bytes": b"",
            "element_graph": {
                "state_id": "vlm",
                "source_backend": "openai_compat_two_pass",
                "source_provider_id": "builtin.vlm.vllm_localhost",
                "ui_state": {"image_size": [7678, 2158]},
                "elements": [
                    {"label": "Task Set up Open Invoice for Contractor Ricardo Lopez for Incident #58476", "bbox": [5694, 513, 7051, 890]},
                    {"label": "COMPLETE", "bbox": [5772, 702, 5955, 739]},
                    {"label": "VIEW DETAILS", "bbox": [5981, 702, 6164, 739]},
                ],
            },
        }
        result = plugin.run_stage("persist.bundle", payload)
        docs = result.get("extra_docs", []) if isinstance(result, dict) else []
        incident = [d for d in docs if isinstance(d, dict) and str(d.get("doc_kind") or "") == "adv.incident.card"]
        self.assertTrue(incident)
        text = str(incident[0].get("text") or "")
        self.assertIn("adv.incident.button.complete_bbox_norm=", text)
        self.assertIn("adv.incident.button.view_details_bbox_norm=", text)
        self.assertIn("\"x1\":0.7518", text)
        self.assertIn("\"y1\":0.3253", text)


if __name__ == "__main__":
    unittest.main()
