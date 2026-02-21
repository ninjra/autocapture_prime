import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autocapture.tools import pillar_gate
from autocapture.pillars.reporting import CheckResult


class PillarGateReportTests(unittest.TestCase):
    def test_reports_written(self) -> None:
        def _fake_check(name, cmd, env, artifacts=(), timeout_s=None):
            return CheckResult(name=name, ok=True, status="pass", duration_ms=1, artifacts=list(artifacts))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with mock.patch.object(pillar_gate, "_run_check", side_effect=_fake_check):
                code = pillar_gate.run_all_gates(artifacts_dir=root, deterministic_fixtures=True)
            self.assertEqual(code, 0)
            report_dir = root / "pillar_reports"
            self.assertTrue((report_dir / "pillar_gates.json").exists())
            self.assertTrue((report_dir / "p1_performant.json").exists())
            self.assertTrue((report_dir / "p2_accurate.json").exists())
            self.assertTrue((report_dir / "p3_secure.json").exists())
            self.assertTrue((report_dir / "p4_citable.json").exists())


if __name__ == "__main__":
    unittest.main()
