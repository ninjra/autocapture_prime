from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.logging import JsonlLogger


class LogCorrelationTests(unittest.TestCase):
    def test_jsonl_logs_include_correlation_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            cfg = {"storage": {"data_dir": str(data_dir)}, "runtime": {"run_id": "run_test"}}
            logger = JsonlLogger.from_config(cfg, name="core")
            logger.event(event="unit.test", run_id="run_test", job_id="job1", plugin_id="plugin.a", x=1)
            lines = Path(logger.path).read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines)
            payload = json.loads(lines[-1])
            self.assertIn("run_id", payload)
            self.assertIn("job_id", payload)
            self.assertIn("plugin_id", payload)
            self.assertEqual(payload["run_id"], "run_test")
            self.assertEqual(payload["job_id"], "job1")
            self.assertEqual(payload["plugin_id"], "plugin.a")


if __name__ == "__main__":
    unittest.main()

