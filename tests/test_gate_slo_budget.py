from __future__ import annotations

import unittest

from tools.gate_slo_budget import _normalize_unknown_statuses


class GateSloBudgetTests(unittest.TestCase):
    def test_normalize_unknown_statuses(self) -> None:
        payload = {
            "overall": "unknown",
            "capture": {"status": "unknown"},
            "query": {"status": "unknown"},
            "processing": {"status": "pass"},
        }
        normalized = _normalize_unknown_statuses(payload)
        self.assertEqual(normalized["overall"], "pass")
        self.assertEqual(normalized["overall_reason"], "no_data")
        self.assertEqual(normalized["capture"]["status"], "pass")
        self.assertEqual(normalized["capture"]["status_reason"], "no_data")
        self.assertEqual(normalized["query"]["status"], "pass")
        self.assertEqual(normalized["processing"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
