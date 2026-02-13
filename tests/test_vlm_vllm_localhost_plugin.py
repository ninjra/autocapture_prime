import unittest

from plugins.builtin.vlm_vllm_localhost.plugin import (
    _collect_rois,
    _extract_layout_from_text,
    _parse_elements,
    _valid_layout,
)


class VllmLocalhostPluginTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
