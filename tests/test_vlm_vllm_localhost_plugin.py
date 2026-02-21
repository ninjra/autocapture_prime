import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.vlm_vllm_localhost.plugin import (
    VllmVLM,
    _adv_fact_topics,
    _collect_rois,
    _extract_layout_from_text,
    _grid_roi_specs,
    _is_model_not_found_error,
    _parse_elements,
    _roi_coverage_bp,
    _valid_layout,
)


class VllmLocalhostPluginTests(unittest.TestCase):
    def _plugin(self) -> VllmVLM:
        ctx = PluginContext(config={}, get_capability=lambda _name: None, logger=lambda _m: None)
        return VllmVLM("builtin.vlm.vllm_localhost", ctx)

    def test_discover_model_ids_returns_ordered_ids(self) -> None:
        class _FakeClient:
            def list_models(self):
                return {"data": [{"id": "m1"}, {"id": "m2"}, {"id": ""}, {"name": "x"}]}

        ids = VllmVLM._discover_model_ids(_FakeClient())  # type: ignore[arg-type]
        self.assertEqual(ids, ["m1", "m2"])

    def test_model_not_found_error_detection(self) -> None:
        self.assertTrue(_is_model_not_found_error("HTTP 404 model does not exist"))
        self.assertTrue(_is_model_not_found_error("model not found"))
        self.assertFalse(_is_model_not_found_error("timeout exceeded"))

    def test_extract_layout_from_fenced_json(self) -> None:
        text = """```json
{"elements":[{"type":"button","bbox":[0,0,10,10],"text":"OK"}]}
```"""
        layout = _extract_layout_from_text(text)
        self.assertTrue(_valid_layout(layout))
        elements = layout.get("elements")
        self.assertIsInstance(elements, list)
        self.assertEqual(elements[0].get("type"), "button")

    def test_extract_layout_rejects_non_json(self) -> None:
        layout = _extract_layout_from_text("not json")
        self.assertFalse(_valid_layout(layout))

    def test_extract_layout_recovers_partial_json(self) -> None:
        text = (
            '```json\n{"elements":[{"type":"window","bbox":[0,0,100,100],"text":"Inbox","children":[{"type":"button"'
        )
        layout = _extract_layout_from_text(text)
        self.assertTrue(_valid_layout(layout))
        self.assertEqual(layout.get("source_backend"), "openai_compat_text_recovered")
        elements = layout.get("elements")
        self.assertIsInstance(elements, list)
        self.assertGreaterEqual(len(elements), 1)

    def test_collect_rois_keeps_full_and_caps_count(self) -> None:
        raw = {
            "rois": [
                {"id": "a", "kind": "window", "label": "A", "bbox_norm": [0.0, 0.0, 1.0, 1.0], "priority": 1.0},
                {"id": "b", "kind": "window", "label": "B", "bbox_norm": [0.1, 0.1, 0.5, 0.5], "priority": 0.8},
            ]
        }
        rois = _collect_rois(raw, width=1000, height=500, max_rois=2)
        self.assertEqual(len(rois), 2)
        self.assertEqual(rois[0].roi_id, "full")

    def test_collect_rois_adds_grid_backstop_when_sparse(self) -> None:
        rois = _collect_rois({}, width=1200, height=600, max_rois=4)
        ids = [r.roi_id for r in rois]
        self.assertEqual(ids[0], "full")
        self.assertGreaterEqual(len(ids), 2)
        self.assertTrue(any(rid.startswith("grid_") for rid in ids[1:]))

    def test_grid_roi_specs_produces_eight_sections(self) -> None:
        specs = _grid_roi_specs(8)
        self.assertEqual(len(specs), 8)
        self.assertEqual(specs[0][0], "grid_1")
        self.assertEqual(specs[-1][0], "grid_8")

    def test_collect_rois_enforces_full_eight_grid_map_reduce(self) -> None:
        rois = _collect_rois({}, width=1600, height=800, max_rois=2, grid_sections=8, grid_enforced=True)
        ids = [r.roi_id for r in rois]
        self.assertEqual(ids[0], "full")
        self.assertTrue(all(f"grid_{idx}" in ids for idx in range(1, 9)))
        self.assertGreaterEqual(len(ids), 9)

    def test_roi_coverage_bp_union_caps_at_full_frame(self) -> None:
        boxes = [(0, 0, 100, 100), (50, 50, 150, 150)]
        bp = _roi_coverage_bp(boxes, width=150, height=150)
        self.assertGreater(bp, 0)
        self.assertLessEqual(bp, 10000)

    def test_parse_elements_maps_roi_local_to_global_pixels(self) -> None:
        roi = _collect_rois({}, width=1000, height=500, max_rois=1)[0]
        child_roi = type(roi)(
            roi_id="test",
            kind="pane",
            label="pane",
            priority_bp=9000,
            bbox_px=(100, 100, 500, 300),
        )
        parsed = _parse_elements(
            {
                "elements": [
                    {
                        "type": "button",
                        "label": "OK",
                        "bbox_norm": [0.25, 0.25, 0.5, 0.5],
                        "state": {"focused": True},
                        "interactable": True,
                    }
                ]
            },
            parent_roi=child_roi,
        )
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["bbox"], [200, 150, 300, 200])
        self.assertEqual(parsed[0]["text"], "OK")

    def test_extract_layout_recovers_partial_rois_windows_and_facts(self) -> None:
        text = (
            '{"rois":[{"id":"r1","kind":"pane","label":"Left","bbox_norm":[0.0,0.0,0.5,1.0],"priority":0.8}],'
            '"windows":[{"label":"Outlook","app":"Microsoft Outlook","context":"vdi","bbox_norm":[0.6,0.1,0.98,0.9],'
            '"visibility":"fully_visible","z_hint":0.7}],'
            '"facts":[{"key":"adv.incident.subject","value":"Task Set Up Open Invoice","confidence":0.99}],"elements":[{"type":"pane"'
        )
        layout = _extract_layout_from_text(text)
        self.assertEqual(layout.get("source_backend"), "openai_compat_text_recovered")
        self.assertIsInstance(layout.get("rois"), list)
        self.assertIsInstance(layout.get("windows"), list)
        self.assertIsInstance(layout.get("facts"), list)
        facts = layout.get("facts", [])
        self.assertTrue(any(isinstance(item, dict) and item.get("key") == "adv.incident.subject" for item in facts))

    def test_adv_fact_topics_extracts_unique_topic_names(self) -> None:
        facts = [
            {"key": "adv.window.1.app", "value": "Slack"},
            {"key": "adv.window.2.app", "value": "Outlook"},
            {"key": "adv.calendar.month_year", "value": "January 2026"},
            {"key": "adv.slack.msg.1.text", "value": "hello"},
            {"key": "other.key", "value": "x"},
        ]
        topics = _adv_fact_topics(facts)
        self.assertIn("window", topics)
        self.assertIn("calendar", topics)
        self.assertIn("slack", topics)
        self.assertNotIn("other", topics)

    def test_circuit_breaker_returns_unavailable_without_crash(self) -> None:
        plugin = self._plugin()
        plugin._mark_chat_failure("http_failed")  # type: ignore[attr-defined]
        plugin._mark_chat_failure("http_failed")  # type: ignore[attr-defined]
        payload = plugin.extract(b"not-an-image")
        self.assertEqual(payload.get("backend"), "unavailable")
        self.assertIn("circuit_open", str(payload.get("model_error") or ""))

    def test_chat_image_retries_on_timeout_then_succeeds(self) -> None:
        plugin = self._plugin()
        plugin._model = "demo-model"  # type: ignore[attr-defined]
        plugin._max_retries = 2  # type: ignore[attr-defined]
        calls = {"count": 0}

        class _FakeClient:
            def chat_completions(self, _req):  # noqa: ANN001
                calls["count"] += 1
                if calls["count"] == 1:
                    raise TimeoutError("timed out")
                return {"choices": [{"message": {"content": "{\"elements\":[]}"}}]}

        content = plugin._chat_image(  # type: ignore[attr-defined]
            _FakeClient(),  # type: ignore[arg-type]
            b"not-a-png",
            "Return JSON",
            max_tokens=64,
            prompt_id="test.timeout.retry",
        )
        self.assertEqual(content, "{\"elements\":[]}")
        self.assertEqual(int(calls["count"]), 2)


if __name__ == "__main__":
    unittest.main()
