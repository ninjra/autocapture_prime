from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from autocapture_nx.kernel.diagnostics_bundle import create_diagnostics_bundle


class DiagnosticsBundleRedactionTests(unittest.TestCase):
    def test_bundle_redacts_gateway_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            cfg = {
                "storage": {"data_dir": str(data_dir)},
                "runtime": {"run_id": "run_test"},
                "gateway": {"openai_api_key": "sk-test-SECRET", "openai_base_url": "https://example.com"},
                "plugins": {"locks": {"lockfile": "config/plugin_locks.json"}},
            }
            report = {"ok": True, "generated_at_utc": "2026-02-08T00:00:00+00:00", "checks": []}
            result = create_diagnostics_bundle(config=cfg, doctor_report=report, out_dir=(Path(tmp) / "out"))
            bundle_path = Path(result.path)
            self.assertTrue(bundle_path.exists())
            with zipfile.ZipFile(bundle_path, "r") as zf:
                text = zf.read("config.snapshot.json").decode("utf-8")
                payload = json.loads(text)
                self.assertEqual(payload.get("gateway", {}).get("openai_api_key"), "[REDACTED]")
                self.assertNotIn("sk-test-SECRET", text)


if __name__ == "__main__":
    unittest.main()

