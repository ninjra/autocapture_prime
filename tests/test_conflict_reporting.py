import unittest

from autocapture.memory.conflict import detect_conflicts


class ConflictReportingTests(unittest.TestCase):
    def test_detects_conflicts(self) -> None:
        claims = [
            {"subject": "device", "value": "on"},
            {"subject": "device", "value": "off"},
        ]
        conflicts = detect_conflicts(claims)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["subject"], "device")


if __name__ == "__main__":
    unittest.main()
