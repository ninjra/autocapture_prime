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


if __name__ == "__main__":
    unittest.main()
