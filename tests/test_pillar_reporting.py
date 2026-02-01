import json
import tempfile
import unittest
from pathlib import Path

from autocapture.pillars.reporting import CheckResult, PillarResult, write_reports


class PillarReportingTests(unittest.TestCase):
    def test_report_files_deterministic(self) -> None:
        checks = [
            CheckResult(name="zeta", ok=False, status="fail", duration_ms=12, artifacts=["b", "a"]),
            CheckResult(name="alpha", ok=True, status="pass", duration_ms=3, artifacts=["c", "b"]),
        ]
        pillar = PillarResult(
            pillar="P1",
            ok=False,
            duration_ms=15,
            started_ts_utc="2026-01-01T00:00:00Z",
            finished_ts_utc="2026-01-01T00:00:01Z",
            checks=checks,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = write_reports("run-123", [pillar], artifacts_dir=root)
            self.assertTrue((root / "pillar_gates.json").exists())
            self.assertTrue((root / "p1_performant.json").exists())

            first = (root / "pillar_gates.json").read_text(encoding="utf-8")
            write_reports("run-123", [pillar], artifacts_dir=root)
            second = (root / "pillar_gates.json").read_text(encoding="utf-8")
            self.assertEqual(first, second)

            payload = json.loads(first)
            self.assertEqual(payload["pillars"][0]["checks"][0]["name"], "alpha")
            self.assertEqual(payload["pillars"][0]["checks"][1]["name"], "zeta")
            self.assertEqual(payload["pillars"][0]["checks"][0]["artifacts"], ["b", "c"])
            self.assertEqual(payload["pillars"][0]["checks"][1]["artifacts"], ["a", "b"])
            self.assertIn("pillar_gates", paths)
            self.assertIn("P1", paths)


if __name__ == "__main__":
    unittest.main()
