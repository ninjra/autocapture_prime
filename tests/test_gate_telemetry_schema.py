from __future__ import annotations

import unittest
from unittest import mock

from tools import gate_telemetry_schema


class GateTelemetrySchemaTests(unittest.TestCase):
    def test_passes_when_no_data(self) -> None:
        with mock.patch.object(gate_telemetry_schema, "telemetry_snapshot", return_value={"latest": {}}):
            rc = gate_telemetry_schema.main()
        self.assertEqual(rc, 0)

    def test_fails_when_required_fields_missing(self) -> None:
        with mock.patch.object(
            gate_telemetry_schema,
            "telemetry_snapshot",
            return_value={"latest": {"capture.output": {"schema_version": 1}}},
        ):
            rc = gate_telemetry_schema.main()
        self.assertEqual(rc, 2)

    def test_passes_when_required_fields_present(self) -> None:
        good = {
            "schema_version": 1,
            "category": "capture.output",
            "ts_utc": "2026-02-18T00:00:00Z",
            "run_id": "",
            "stage": "write",
            "duration_ms": 1.0,
            "outcome": "ok",
            "error_code": "",
        }
        with mock.patch.object(gate_telemetry_schema, "telemetry_snapshot", return_value={"latest": {"capture.output": good}}):
            rc = gate_telemetry_schema.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()

