from __future__ import annotations

import unittest

from autocapture_prime.ingest.normalize import qpc_to_relative_seconds


class ChronicleTimeNormalizationTests(unittest.TestCase):
    def test_qpc_relative_seconds(self) -> None:
        value = qpc_to_relative_seconds(2_500_000, 1_000_000, 1_000_000)
        self.assertAlmostEqual(value, 1.5)

    def test_zero_frequency_returns_zero(self) -> None:
        self.assertEqual(qpc_to_relative_seconds(10, 0, 0), 0.0)


if __name__ == "__main__":
    unittest.main()
