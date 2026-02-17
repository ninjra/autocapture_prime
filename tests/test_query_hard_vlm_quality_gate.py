import unittest

from autocapture_nx.kernel import query as query_mod


class QueryHardVlmQualityGateTests(unittest.TestCase):
    def test_action_grounding_rejects_invalid_boxes(self) -> None:
        ok, reason, bp = query_mod._hard_vlm_quality_gate(
            "hard_action_grounding",
            {
                "COMPLETE": {"x1": 0.15, "y1": 0.20, "x2": 0.18, "y2": 0.205},
                "VIEW_DETAILS": {"x1": 0.10, "y1": 0.30, "x2": 0.13, "y2": 0.33},
            },
        )
        self.assertFalse(ok)
        self.assertTrue(reason)
        self.assertLess(bp, 3000)

    def test_action_grounding_accepts_reasonable_boxes(self) -> None:
        ok, reason, bp = query_mod._hard_vlm_quality_gate(
            "hard_action_grounding",
            {
                "COMPLETE": {"x1": 0.73, "y1": 0.32, "x2": 0.78, "y2": 0.34},
                "VIEW_DETAILS": {"x1": 0.80, "y1": 0.32, "x2": 0.87, "y2": 0.34},
            },
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertGreaterEqual(bp, 8000)

    def test_hard_fields_substantive_false_when_quality_gate_fails(self) -> None:
        self.assertFalse(
            query_mod._hard_fields_have_substantive_content(
                "adv_incident",
                {"subject": "Task Set Up Open Invoice", "_quality_gate_ok": False},
            )
        )

    def test_prioritize_topic_candidates_prefers_roi(self) -> None:
        ranked = query_mod._prioritize_topic_vlm_candidates(
            "hard_action_grounding",
            [
                {"source": "grid8", "section_id": "grid_1", "roi": (0, 0, 100, 100)},
                {"source": "roi", "section_id": "", "roi": (600, 200, 760, 260)},
                {"source": "full", "section_id": "", "roi": None},
            ],
        )
        self.assertEqual(str(ranked[0].get("source")), "roi")

    def test_hard_k_presets_hint_hydration(self) -> None:
        hydrated = query_mod._hard_k_presets_from_hint(
            {"k_presets": [], "clamp_range_inclusive": []},
            "Added k preset buttons (32/64/128) and server-side clamp (1-200).",
        )
        self.assertEqual(hydrated.get("k_presets"), [32, 64, 128])
        self.assertEqual(hydrated.get("k_presets_sum"), 224)
        self.assertEqual(hydrated.get("clamp_range_inclusive"), [1, 200])
        validity = hydrated.get("preset_validity")
        self.assertIsInstance(validity, list)
        self.assertEqual(len(validity), 3)
        self.assertTrue(all(bool(item.get("valid")) for item in validity if isinstance(item, dict)))

    def test_normalize_hard_fields_recovers_embedded_json(self) -> None:
        normalized = query_mod._normalize_hard_fields_for_topic(
            "adv_focus",
            {
                "answer_text": 'model said: {"focused_window":"Outlook VDI","evidence":[{"kind":"selected","text":"Task Set Up Open Invoice"}]}',
            },
        )
        self.assertEqual(normalized.get("focused_window"), "Outlook VDI")
        evidence = normalized.get("evidence")
        self.assertIsInstance(evidence, list)
        self.assertGreaterEqual(len(evidence), 1)

    def test_grid_section_boxes_supports_twelve_segments(self) -> None:
        boxes = query_mod._grid_section_boxes(7680, 2160, sections=12)
        self.assertEqual(len(boxes), 12)
        self.assertEqual(len(set(boxes)), 12)
        # Deterministic row-major ordering: first row starts at y=0, second row below it.
        self.assertEqual(boxes[0][1], 0)
        self.assertGreaterEqual(boxes[4][1], boxes[0][3])

    def test_unread_topic_rois_are_not_truncated_to_five(self) -> None:
        width, height = 7680, 2160
        boxes = query_mod._topic_roi_boxes("hard_unread_today", [], width=width, height=height)
        self.assertGreaterEqual(len(boxes), 4)
        # Ensure dedicated unread-list slice exists in the right pane.
        self.assertTrue(any(b[0] >= int(width * 0.64) and b[2] >= int(width * 0.80) for b in boxes))


if __name__ == "__main__":
    unittest.main()
