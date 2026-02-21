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


if __name__ == "__main__":
    unittest.main()
