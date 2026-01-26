import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.loader import Kernel


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

    def test_crash_entry_on_next_boot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            kernel = Kernel(paths, safe_mode=False)
            kernel.boot()
            # Intentionally skip shutdown to simulate crash.
            kernel2 = Kernel(paths, safe_mode=False)
            kernel2.boot()
            kernel2.shutdown()
            ledger_path = Path(tmp) / "data" / "ledger.ndjson"
            entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            events = [entry.get("payload", {}).get("event") for entry in entries]
            self.assertIn("system.crash", events)


if __name__ == "__main__":
    unittest.main()
