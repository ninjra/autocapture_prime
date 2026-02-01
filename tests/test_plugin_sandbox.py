import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.sandbox import SandboxReport, validate_ipc_message, write_sandbox_report


class PluginSandboxTests(unittest.TestCase):
    def test_ipc_validation(self) -> None:
        ok, _ = validate_ipc_message({"method": "call", "capability": "x", "function": "y"}, role="plugin")
        self.assertTrue(ok)
        ok, reason = validate_ipc_message({"method": "unknown"}, role="plugin")
        self.assertFalse(ok)
        self.assertEqual(reason, "unknown_method")

    def test_sandbox_report_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = SandboxReport(
                pid=123,
                restricted_token=False,
                job_object=True,
                ipc_schema_enforced=True,
                ipc_max_bytes=1024,
                notes=("test",),
            )
            path = Path(tmp) / "report.json"
            write_sandbox_report(report, path=path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("pid"), 123)
            self.assertTrue(payload.get("job_object"))


if __name__ == "__main__":
    unittest.main()
