from __future__ import annotations

import unittest

from autocapture_nx.kernel.telemetry import TelemetryStore, normalize_telemetry_payload


class TelemetrySchemaTests(unittest.TestCase):
    def test_normalize_populates_required_fields(self) -> None:
        row = normalize_telemetry_payload("processing.idle", {"duration_ms": 12, "stage": "idle.extract"})
        self.assertEqual(row.get("schema_version"), 1)
        self.assertEqual(row.get("category"), "processing.idle")
        self.assertEqual(row.get("stage"), "idle.extract")
        self.assertEqual(row.get("outcome"), "ok")
        self.assertEqual(float(row.get("duration_ms") or 0.0), 12.0)
        self.assertIn("ts_utc", row)

    def test_normalize_sets_error_outcome_when_error_code_exists(self) -> None:
        row = normalize_telemetry_payload("query.answer", {"error_code": "timeout", "duration_ms": -5})
        self.assertEqual(row.get("outcome"), "error")
        self.assertEqual(row.get("error_code"), "timeout")
        self.assertEqual(float(row.get("duration_ms") or 0.0), 0.0)

    def test_store_records_normalized_rows(self) -> None:
        store = TelemetryStore(max_samples=2)
        store.record("capture.pipeline", {"stage": "ingest", "duration_ms": 7.5})
        snap = store.snapshot()
        latest = snap.get("latest", {}).get("capture.pipeline", {})
        self.assertEqual(latest.get("schema_version"), 1)
        self.assertEqual(latest.get("stage"), "ingest")
        self.assertEqual(latest.get("outcome"), "ok")


if __name__ == "__main__":
    unittest.main()

