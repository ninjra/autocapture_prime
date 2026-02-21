import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.loader import Kernel
from autocapture_nx.plugin_system.runtime import global_network_deny, set_global_network_deny


def _paths(tmp: str) -> ConfigPaths:
    root = Path(tmp)
    default_path = root / "default.json"
    schema_path = root / "schema.json"
    user_path = root / "user.json"
    backup_dir = root / "backup"
    with open("config/default.json", "r", encoding="utf-8") as handle:
        default = json.load(handle)
    with open(default_path, "w", encoding="utf-8") as handle:
        json.dump(default, handle, indent=2, sort_keys=True)
    with open("contracts/config_schema.json", "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    with open(schema_path, "w", encoding="utf-8") as handle:
        json.dump(schema, handle, indent=2, sort_keys=True)
    user_override = {
        "paths": {
            "config_dir": str(root),
            "data_dir": str(root / "data"),
        },
        "storage": {
            "data_dir": str(root / "data"),
            "crypto": {
                "keyring_path": str(root / "data" / "vault" / "keyring.json"),
                "root_key_path": str(root / "data" / "vault" / "root.key"),
            },
        },
        "plugins": {
            "enabled": {
                "builtin.capture.windows": False,
                "builtin.capture.audio.windows": False,
                "builtin.tracking.input.windows": False,
                "builtin.window.metadata.windows": False,
            }
        },
    }
    with open(user_path, "w", encoding="utf-8") as handle:
        json.dump(user_override, handle)
    return ConfigPaths(default_path, user_path, schema_path, backup_dir)


class RunStateEntryTests(unittest.TestCase):
    def test_start_and_stop_entries_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            kernel = Kernel(paths, safe_mode=False)
            kernel.boot()
            kernel.shutdown()
            ledger_path = Path(tmp) / "data" / "ledger.ndjson"
            self.assertTrue(ledger_path.exists())
            entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            events = {entry.get("payload", {}).get("event") for entry in entries}
            self.assertIn("system.start", events)
            self.assertIn("system.stop", events)
            start_entries = [entry for entry in entries if entry.get("payload", {}).get("event") == "system.start"]
            stop_entries = [entry for entry in entries if entry.get("payload", {}).get("event") == "system.stop"]
            self.assertTrue(start_entries)
            self.assertTrue(stop_entries)
            start_payload = start_entries[-1]["payload"]
            self.assertIn("config", start_payload)
            self.assertIn("locks", start_payload)
            self.assertIn("kernel_version", start_payload)
            self.assertEqual(start_payload.get("run_id"), kernel.config.get("runtime", {}).get("run_id"))
            stop_payload = stop_entries[-1]["payload"]
            self.assertIn("duration_ms", stop_payload)
            self.assertIsInstance(stop_payload.get("duration_ms"), int)
            self.assertIn("summary", stop_payload)
            summary = stop_payload.get("summary", {})
            self.assertIsInstance(summary.get("events"), int)
            self.assertIsInstance(summary.get("drops"), int)
            self.assertIsInstance(summary.get("errors"), int)

    def test_crash_entry_on_next_boot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prev_deny = global_network_deny()
            paths = _paths(tmp)
            kernel = Kernel(paths, safe_mode=False)
            try:
                kernel.boot()
                # Intentionally skip shutdown to simulate crash.
                # A real crash releases OS locks; emulate that without emitting a
                # clean shutdown entry.
                try:
                    if kernel.system is not None:
                        kernel.system.close()
                except Exception:
                    pass
                try:
                    if kernel._instance_lock is not None:
                        kernel._instance_lock.close()
                except Exception:
                    pass
                kernel2 = Kernel(paths, safe_mode=False)
                kernel2.boot()
                kernel2.shutdown()
            finally:
                set_global_network_deny(prev_deny)
            ledger_path = Path(tmp) / "data" / "ledger.ndjson"
            entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            events = [entry.get("payload", {}).get("event") for entry in entries]
            self.assertIn("system.crash_detected", events)
            crash_entries = [
                entry for entry in entries if entry.get("payload", {}).get("event") == "system.crash_detected"
            ]
            self.assertTrue(crash_entries)
            crash_payload = crash_entries[-1]["payload"]
            self.assertIn("previous_run_id", crash_payload)
            self.assertIn("previous_state_ts_utc", crash_payload)


if __name__ == "__main__":
    unittest.main()
