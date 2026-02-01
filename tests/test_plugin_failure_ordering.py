import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.audit import PluginAuditLog
from autocapture_nx.plugin_system.registry import PluginRegistry, CapabilityProxy


class PluginFailureOrderingTests(unittest.TestCase):
    def test_failure_history_orders_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
            audit_path = Path(tmp) / "audit.db"
            config.setdefault("storage", {})["audit_db_path"] = str(audit_path)
            config.setdefault("runtime", {})["run_id"] = "run-test"
            config.setdefault("plugins", {})["failure_ordering"] = {"enabled": True, "min_calls": 1}

            audit = PluginAuditLog.from_config(config)
            for _ in range(2):
                audit.record(
                    run_id="run-test",
                    plugin_id="plugin.bad",
                    capability="test.cap",
                    method="call",
                    ok=False,
                    error="boom",
                    duration_ms=1,
                    rows_read=None,
                    rows_written=None,
                    memory_rss_mb=None,
                    memory_vms_mb=None,
                    input_hash=None,
                    output_hash=None,
                    data_hash=None,
                    code_hash=None,
                    settings_hash=None,
                    input_bytes=None,
                    output_bytes=None,
                )
            for _ in range(2):
                audit.record(
                    run_id="run-test",
                    plugin_id="plugin.good",
                    capability="test.cap",
                    method="call",
                    ok=True,
                    error=None,
                    duration_ms=1,
                    rows_read=None,
                    rows_written=None,
                    memory_rss_mb=None,
                    memory_vms_mb=None,
                    input_hash=None,
                    output_hash=None,
                    data_hash=None,
                    code_hash=None,
                    settings_hash=None,
                    input_bytes=None,
                    output_bytes=None,
                )

            registry = PluginRegistry(config, safe_mode=False)
            providers = [
                ("plugin.bad", CapabilityProxy(lambda: None, False, None)),
                ("plugin.good", CapabilityProxy(lambda: None, False, None)),
            ]
            policy = registry._capability_policy("test.cap")
            ordered = registry._ordered_providers(providers, policy)
            self.assertEqual(ordered[0][0], "plugin.good")


if __name__ == "__main__":
    unittest.main()
