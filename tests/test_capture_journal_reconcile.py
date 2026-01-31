import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
from autocapture_nx.kernel.loader import Kernel
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.storage_sqlcipher.plugin import SQLCipherStoragePlugin


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
        "runtime": {"run_id": "run1", "timezone": "UTC"},
        "storage": {
            "data_dir": str(root / "data"),
            "spool_dir": str(root / "data" / "spool"),
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


class CaptureJournalReconcileTests(unittest.TestCase):
    def test_reconcile_marks_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            data_dir = Path(tmp) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            record_id = "run1/segment/0"
            journal_path = data_dir / "journal.ndjson"
            event = {
                "event_id": "evt1",
                "event_type": "capture.stage",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "payload": {"record_id": record_id, "record_type": "evidence.capture.segment"},
            }
            journal_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

            kernel = Kernel(paths, safe_mode=False)
            kernel.boot()
            kernel.shutdown()

            config = load_config(paths, safe_mode=False)
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            storage = SQLCipherStoragePlugin("builtin.storage.sqlcipher", ctx)
            metadata = storage.capabilities()["storage.metadata"]

            unavailable = []
            for key in metadata.keys():
                payload = metadata.get(key)
                if isinstance(payload, dict) and payload.get("record_type") == "evidence.capture.unavailable":
                    unavailable.append(payload)
            self.assertTrue(unavailable, "expected unavailable records after reconcile")
            parent_ids = {record.get("parent_evidence_id") for record in unavailable}
            self.assertIn(record_id, parent_ids)


if __name__ == "__main__":
    unittest.main()
