import unittest

from plugins.builtin.vlm_qwen2_vl_2b.plugin import (
    _dedupe_elements,
    _dedupe_facts,
    _dedupe_windows,
    _extract_json,
    _norm_bbox_to_px,
)


class Qwen2Vl2BPluginUnitTests(unittest.TestCase):
    def test_extract_json_from_fence(self) -> None:
        raw = """```json
{"rois":[{"id":"r1","bbox_norm":[0.1,0.2,0.3,0.4]}]}
```"""
        parsed = _extract_json(raw)
        self.assertIn("rois", parsed)

    def test_norm_bbox_to_px(self) -> None:
        bbox = _norm_bbox_to_px([0.1, 0.2, 0.9, 0.8], width=1000, height=500)
        self.assertEqual(bbox, (100, 100, 900, 400))

    def test_dedupe_elements(self) -> None:
        items = [
            {"id": "a", "type": "text", "bbox": [10, 10, 100, 40], "label": "Inbox", "source_roi": "r1"},
            {"id": "b", "type": "text", "bbox": [11, 10, 100, 40], "label": "Inbox", "source_roi": "r2"},
        ]
        out = _dedupe_elements(items)
        self.assertEqual(len(out), 1)

    def test_dedupe_windows(self) -> None:
        items = [
            {
                "window_id": "w1",
                "label": "Outlook",
                "app": "Outlook",
                "context": "vdi",
                "visibility": "fully_visible",
                "z_hint_bp": 9000,
                "bbox": [100, 100, 600, 500],
            },
            {
                "window_id": "w2",
                "label": "Outlook",
                "app": "Outlook",
                "context": "vdi",
                "visibility": "partially_occluded",
                "z_hint_bp": 8000,
                "bbox": [102, 102, 598, 498],
            },
        ]
        out = _dedupe_windows(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].get("app"), "Outlook")

    def test_dedupe_facts(self) -> None:
        items = [
            {"fact_id": "f1", "key": "open_inboxes", "value": "4", "confidence_bp": 9000},
            {"fact_id": "f2", "key": "open_inboxes", "value": "4", "confidence_bp": 7000},
        ]
        out = _dedupe_facts(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].get("value"), "4")


if __name__ == "__main__":
    unittest.main()
