import json
import tempfile
import unittest
import hashlib
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
from autocapture_nx.kernel.loader import Kernel
from autocapture_nx.kernel.hashing import sha256_canonical
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


class StorageRecoveryScannerTests(unittest.TestCase):
    def test_recovery_removes_tmp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            data_dir = Path(tmp) / "data"
            spool_dir = data_dir / "spool"
            spool_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = spool_dir / "segment.tmp"
            tmp_file.write_text("partial", encoding="utf-8")

            kernel = Kernel(paths, safe_mode=False)
            kernel.boot()
            kernel.shutdown()

            self.assertFalse(tmp_file.exists())

            ledger_path = data_dir / "ledger.ndjson"
            entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            events = [entry.get("payload", {}).get("event") for entry in entries]
            self.assertIn("storage.recovery", events)

    def test_recovery_seals_unsealed_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            config = load_config(paths, safe_mode=False)
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            storage = SQLCipherStoragePlugin("builtin.storage.sqlcipher", ctx)
            caps = storage.capabilities()
            metadata = caps["storage.metadata"]
            media = caps["storage.media"]

            record_id = "run1/segment/0"
            ts_utc = "2024-01-01T00:00:00+00:00"
            payload = b"segment-data"
            if hasattr(media, "put_new"):
                media.put_new(record_id, payload, ts_utc=ts_utc)
            else:
                media.put(record_id, payload, ts_utc=ts_utc)
            meta_payload = {
                "record_type": "evidence.capture.segment",
                "run_id": "run1",
                "segment_id": record_id,
                "ts_start_utc": ts_utc,
                "ts_end_utc": ts_utc,
                "content_hash": hashlib.sha256(payload).hexdigest(),
            }
            meta_payload["payload_hash"] = sha256_canonical(
                {k: v for k, v in meta_payload.items() if k != "payload_hash"}
            )
            if hasattr(metadata, "put_new"):
                metadata.put_new(record_id, meta_payload)
            else:
                metadata.put(record_id, meta_payload)

            kernel = Kernel(paths, safe_mode=False)
            kernel.boot()
            kernel.shutdown()

            ledger_path = Path(tmp) / "data" / "ledger.ndjson"
            entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            seal_events = [entry.get("payload", {}).get("event") for entry in entries if entry.get("payload")]
            self.assertIn("segment.sealed", seal_events)


if __name__ == "__main__":
    unittest.main()
