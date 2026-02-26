from __future__ import annotations

import unittest

from autocapture_nx.kernel import query as query_mod


class QueryIntentRoutingTests(unittest.TestCase):
    def test_intent_detects_advanced_window_inventory(self) -> None:
        intent = query_mod._query_intent(  # type: ignore[attr-defined]
            "Enumerate every distinct top-level window visible in front-to-back z-order"
        )
        self.assertEqual(intent.get("topic"), "adv_window_inventory")
        self.assertEqual(intent.get("family"), "advanced")
        self.assertGreater(float(intent.get("score", 0.0)), 0.0)

    def test_intent_detects_hard_action_grounding(self) -> None:
        intent = query_mod._query_intent(  # type: ignore[attr-defined]
            "Action grounding: provide normalized bounding boxes for COMPLETE and VIEW DETAILS"
        )
        self.assertEqual(intent.get("topic"), "hard_action_grounding")
        self.assertEqual(intent.get("family"), "hard")

    def test_intent_falls_back_to_generic(self) -> None:
        intent = query_mod._query_intent(  # type: ignore[attr-defined]
            "Tell me something unrelated to visual extraction classes"
        )
        self.assertEqual(intent.get("topic"), "generic")
        self.assertEqual(intent.get("family"), "generic")

    def test_intent_is_stable_for_paraphrases(self) -> None:
        a = query_mod._query_intent(  # type: ignore[attr-defined]
            "List all visible top-level windows and their occlusion order."
        )
        b = query_mod._query_intent(  # type: ignore[attr-defined]
            "Enumerate distinct windows front-to-back with overlap status."
        )
        self.assertEqual(a.get("topic"), "adv_window_inventory")
        self.assertEqual(b.get("topic"), "adv_window_inventory")

    def test_intent_detects_hard_cross_window_sizes_for_generic13_style_query(self) -> None:
        intent = query_mod._query_intent(  # type: ignore[attr-defined]
            "Identify two numeric values referenced in one communication panel, infer their best matching parameter name from technical notes, and produce example request query strings using those values."
        )
        self.assertEqual(intent.get("topic"), "hard_cross_window_sizes")
        self.assertEqual(intent.get("family"), "hard")

    def test_intent_detects_temporal_analytics_for_rolling_window_question(self) -> None:
        intent = query_mod._query_intent(  # type: ignore[attr-defined]
            "In the last 24 hours, what unique top-level windows were visible, and for each what were first_seen and last_seen times?"
        )
        self.assertEqual(intent.get("topic"), "temporal_analytics")
        self.assertEqual(intent.get("family"), "temporal")

    def test_intent_detects_temporal_analytics_for_grounded_ts_utc_question(self) -> None:
        intent = query_mod._query_intent(  # type: ignore[attr-defined]
            "Convert the on-screen ts_utc value to America/Denver local time (include offset)."
        )
        self.assertEqual(intent.get("topic"), "temporal_analytics")
        self.assertEqual(intent.get("family"), "temporal")

    def test_intent_detects_temporal_analytics_for_grounded_pytest_question(self) -> None:
        intent = query_mod._query_intent(  # type: ignore[attr-defined]
            "What pytest result line is shown (tests passed and total runtime)?"
        )
        self.assertEqual(intent.get("topic"), "temporal_analytics")
        self.assertEqual(intent.get("family"), "temporal")

    def test_intent_detects_temporal_analytics_for_grounded_investigating_duration(self) -> None:
        intent = query_mod._query_intent(  # type: ignore[attr-defined]
            "What duration is shown for `Investigating error source`?"
        )
        self.assertEqual(intent.get("topic"), "temporal_analytics")
        self.assertEqual(intent.get("family"), "temporal")

    def test_intent_keeps_adv_details_for_kv_extraction_query(self) -> None:
        intent = query_mod._query_intent(  # type: ignore[attr-defined]
            "From the 'Details' section, extract all visible field labels and values as key-value pairs."
        )
        self.assertEqual(intent.get("topic"), "adv_details")
        self.assertEqual(intent.get("family"), "advanced")


if __name__ == "__main__":
    unittest.main()
