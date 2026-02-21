import json
import tempfile
import unittest
from pathlib import Path

from autocapture.storage.forecast import forecast_from_journal


class StorageForecastTests(unittest.TestCase):
    def test_forecast_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "journal.ndjson"
            entries = [
                {
                    "event_type": "disk.pressure",
                    "ts_utc": "2024-01-01T00:00:00+00:00",
                    "payload": {"free_bytes": 1000, "evidence_bytes": 2000, "derived_bytes": 100},
                },
                {
                    "event_type": "disk.pressure",
                    "ts_utc": "2024-01-02T00:00:00+00:00",
                    "payload": {"free_bytes": 500, "evidence_bytes": 2500, "derived_bytes": 200},
                },
            ]
            journal.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
            result = forecast_from_journal(tmp)
            self.assertEqual(result.samples, 2)
            self.assertEqual(result.days_remaining, 1)
            self.assertEqual(result.trend_bytes_per_day, -500)
            self.assertEqual(result.evidence_bytes_per_day, 500)
            self.assertEqual(result.derived_bytes_per_day, 100)


if __name__ == "__main__":
    unittest.main()
