import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.observation_graph.plugin import (
    ObservationGraphPlugin,
    _filter_adv_fact_map,
    _looks_like_layout_json,
    _windows_from_ui_state,
)


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
            "text_lines": [
                {
                    "text": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476 Permian Resources Service Desk permian.xyz.com COMPLETE VIEW DETAILS",
                    "bbox": [0, 0, 600, 20],
                }
            ],
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

    def test_adv_incident_uses_ui_fact_overrides_when_present(self) -> None:
        plugin = self._plugin()
        payload = {
            "text_lines": [
                {
                    "text": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476 Permian Resources Service Desk permian.xyz.com COMPLETE VIEW DETAILS",
                    "bbox": [0, 0, 600, 20],
                }
            ],
            "extra_docs": [],
            "tokens_raw": [],
            "frame_bytes": b"",
            "element_graph": {
                "state_id": "vlm",
                "source_backend": "openai_compat_two_pass",
                "source_provider_id": "builtin.vlm.vllm_localhost",
                "elements": [
                    {"label": "placeholder", "bbox": [0, 0, 100, 100]},
                    {"label": "placeholder2", "bbox": [100, 100, 200, 200]},
                ],
                "ui_state": {
                    "facts": [
                        {"key": "adv.incident.subject", "value": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476", "confidence": 0.99},
                        {"key": "adv.incident.sender_display", "value": "Permian Resources Service Desk", "confidence": 0.99},
                        {"key": "adv.incident.sender_domain", "value": "permian.xyz.com", "confidence": 0.99},
                        {"key": "adv.incident.action_buttons", "value": "COMPLETE|VIEW DETAILS", "confidence": 0.99},
                    ]
                },
            },
        }
        result = plugin.run_stage("persist.bundle", payload)
        docs = result.get("extra_docs", []) if isinstance(result, dict) else []
        incident = [d for d in docs if isinstance(d, dict) and str(d.get("doc_kind") or "") == "adv.incident.card"]
        self.assertTrue(incident)
        text = str(incident[0].get("text") or "")
        self.assertIn("adv.incident.subject=Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident 58476", text)
        self.assertIn("adv.incident.sender_domain=permian.xyz.com", text)
        self.assertIn("adv.incident.action_buttons=COMPLETE|VIEW DETAILS", text)

    def test_adv_incident_uses_top_level_fact_overrides_when_ui_state_missing(self) -> None:
        plugin = self._plugin()
        payload = {
            "text_lines": [
                {
                    "text": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476 Permian Resources Service Desk permian.xyz.com COMPLETE VIEW DETAILS",
                    "bbox": [0, 0, 600, 20],
                }
            ],
            "extra_docs": [],
            "tokens_raw": [],
            "frame_bytes": b"",
            "element_graph": {
                "state_id": "vlm",
                "source_backend": "openai_compat_two_pass",
                "source_provider_id": "builtin.vlm.vllm_localhost",
                "elements": [
                    {"label": "placeholder", "bbox": [0, 0, 100, 100]},
                    {"label": "placeholder2", "bbox": [100, 100, 200, 200]},
                ],
                "facts": [
                    {"key": "adv.incident.subject", "value": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476", "confidence_bp": 9900},
                    {"key": "adv.incident.sender_display", "value": "Permian Resources Service Desk", "confidence_bp": 9900},
                    {"key": "adv.incident.sender_domain", "value": "permian.xyz.com", "confidence_bp": 9900},
                    {"key": "adv.incident.action_buttons", "value": "COMPLETE|VIEW DETAILS", "confidence_bp": 9900},
                ],
            },
        }
        result = plugin.run_stage("persist.bundle", payload)
        docs = result.get("extra_docs", []) if isinstance(result, dict) else []
        incident = [d for d in docs if isinstance(d, dict) and str(d.get("doc_kind") or "") == "adv.incident.card"]
        self.assertTrue(incident)
        text = str(incident[0].get("text") or "")
        self.assertIn("adv.incident.subject=Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident 58476", text)
        self.assertIn("adv.incident.sender_domain=permian.xyz.com", text)
        self.assertIn("adv.incident.action_buttons=COMPLETE|VIEW DETAILS", text)

    def test_window_inventory_uses_element_windows_without_ui_state_windows(self) -> None:
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
                "elements": [
                    {"element_id": "root", "type": "window", "label": "", "bbox": [0, 0, 7678, 2158]},
                    {"element_id": "w1", "type": "window", "label": "Slack DM", "bbox": [2200, 320, 4300, 980], "z": 3},
                    {"element_id": "w2", "type": "window", "label": "Outlook (VDI)", "bbox": [5400, 120, 7678, 2100], "z": 2},
                ],
                "facts": [
                    {"key": "adv.window.app", "value": "Task List", "confidence_bp": 10000},
                    {"key": "adv.window.context", "value": "host", "confidence_bp": 10000},
                ],
            },
        }
        result = plugin.run_stage("persist.bundle", payload)
        docs = result.get("extra_docs", []) if isinstance(result, dict) else []
        windows = [d for d in docs if isinstance(d, dict) and str(d.get("doc_kind") or "") == "adv.window.inventory"]
        self.assertTrue(windows)
        text = str(windows[0].get("text") or "")
        self.assertIn("adv.window.1.app=Slack DM", text)
        self.assertIn("adv.window.2.app=Outlook VDI", text)
        self.assertNotIn("adv.window.app=Task List", text)

    def test_filter_adv_fact_map_drops_ungrounded_fact_values(self) -> None:
        fact_map = {
            "adv.calendar.month_year": "October 2023",
            "adv.calendar.item_count": "5",
            "adv.calendar.item.N.title": "Not found",
            "adv.incident.subject": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
            "adv.incident.sender_domain": "example.com",
        }
        corpus = "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476 January 2026"
        filtered = _filter_adv_fact_map(fact_map, corpus)
        self.assertNotIn("adv.calendar.month_year", filtered)
        self.assertNotIn("adv.calendar.item.N.title", filtered)
        self.assertNotIn("adv.incident.sender_domain", filtered)
        self.assertEqual(filtered.get("adv.calendar.item_count"), "5")
        self.assertIn("adv.incident.subject", filtered)

    def test_adv_fact_grounding_ignores_vision_vlm_text_as_ground_truth(self) -> None:
        plugin = self._plugin()
        payload = {
            "text_lines": [{"text": "Unrelated OCR text only", "bbox": [0, 0, 200, 20]}],
            "extra_docs": [
                {
                    "stage": "vision.vlm",
                    "text": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
                }
            ],
            "tokens_raw": [],
            "frame_bytes": b"",
            "element_graph": {
                "state_id": "vlm",
                "source_backend": "openai_compat_two_pass",
                "source_provider_id": "builtin.vlm.vllm_localhost",
                "elements": [
                    {"label": "placeholder", "bbox": [0, 0, 100, 100]},
                    {"label": "placeholder2", "bbox": [100, 100, 200, 200]},
                ],
                "ui_state": {
                    "facts": [
                        {"key": "adv.incident.subject", "value": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476", "confidence": 0.99},
                    ]
                },
            },
        }
        result = plugin.run_stage("persist.bundle", payload)
        docs = result.get("extra_docs", []) if isinstance(result, dict) else []
        incident = [d for d in docs if isinstance(d, dict) and str(d.get("doc_kind") or "") == "adv.incident.card"]
        self.assertFalse(incident)

    def test_layout_json_line_detection(self) -> None:
        self.assertTrue(_looks_like_layout_json('{"elements":[{"type":"window"}]}'))
        self.assertTrue(_looks_like_layout_json('{"windows":[{"app":"Outlook"}]}'))
        self.assertFalse(_looks_like_layout_json("Task Set Up Open Invoice"))

    def test_windows_from_ui_state_fail_closed_on_missing_or_canvas_bbox(self) -> None:
        ui_state = {
            "windows": [
                {"window_id": "canvas", "app": "Canvas", "bbox": [0, 0, 1000, 1000], "context": "host"},
                {"window_id": "good", "app": "Slack", "bbox": [120, 80, 900, 620], "context": "host"},
                {"window_id": "missing", "app": "NoBBox"},
            ]
        }
        windows = _windows_from_ui_state(ui_state, max_x=1000, max_y=1000)
        self.assertEqual(len(windows), 1)
        self.assertEqual(str(windows[0].get("window_id") or ""), "good")

    def test_provider_identity_restores_vlm_grounding_when_state_id_rewritten(self) -> None:
        plugin = self._plugin()
        payload = {
            "text_lines": [{"text": "Now playing: Master Cylinder - Jung At Heart", "bbox": [10, 10, 300, 28]}],
            "extra_docs": [],
            "tokens_raw": [],
            "frame_bytes": b"",
            "element_graph": {
                "state_id": "rid_abc123",
                "source_backend": "openai_compat_two_pass",
                "source_provider_id": "builtin.vlm.vllm_localhost",
                "elements": [
                    {"label": "Now playing: Master Cylinder - Jung At Heart", "bbox": [10, 10, 300, 28]},
                    {"label": "SiriusXM", "bbox": [20, 40, 300, 70]},
                ],
            },
        }
        result = plugin.run_stage("persist.bundle", payload)
        docs = result.get("extra_docs", []) if isinstance(result, dict) else []
        media = [d for d in docs if isinstance(d, dict) and str(d.get("doc_kind") or "") == "obs.media.now_playing"]
        self.assertTrue(media)
        meta = media[0].get("meta", {}) if isinstance(media[0].get("meta"), dict) else {}
        self.assertEqual(str(meta.get("source_modality") or ""), "vlm")


if __name__ == "__main__":
    unittest.main()
