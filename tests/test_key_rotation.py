import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.key_rotation import rotate_keys
from autocapture_nx.kernel.loader import Kernel


class KeyRotationTests(unittest.TestCase):
    def test_rotate_preserves_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ConfigPaths(
                default_path=Path("config") / "default.json",
                user_path=Path(tmp) / "user.json",
                schema_path=Path("contracts") / "config_schema.json",
                backup_dir=Path(tmp) / "backup",
            )
            safe_tmp = tmp.replace("\\", "/")
            user_override = {
                "storage": {
                    "data_dir": safe_tmp,
                    "crypto": {
                        "keyring_path": f"{safe_tmp}/keyring.json",
                        "root_key_path": f"{safe_tmp}/root.key",
                    },
                },
                "plugins": {
                    "enabled": {
                        "builtin.storage.sqlcipher": False,
                        "builtin.storage.encrypted": True,
                        "builtin.capture.windows": False,
                        "builtin.capture.audio.windows": False,
                        "builtin.tracking.input.windows": False,
                        "builtin.window.metadata.windows": False,
                    }
                },
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(user_override, handle)
            kernel = Kernel(paths, safe_mode=False)
            system = kernel.boot()
            try:
                store = system.get("storage.metadata")
                store.put("rec1", {"record_type": "derived.test", "run_id": "run1", "content_hash": "hash", "value": 123})
                self.assertEqual(store.get("rec1")["value"], 123)
                rotate_keys(system)
                self.assertEqual(store.get("rec1")["value"], 123)
                data_dir = safe_tmp
                if isinstance(kernel.config, dict):
                    data_dir = str(kernel.config.get("storage", {}).get("data_dir") or safe_tmp)
                ledger_path = Path(data_dir) / "ledger.ndjson"
                entries = []
                if ledger_path.exists():
                    with open(ledger_path, "r", encoding="utf-8") as handle:
                        for line in handle:
                            if not line.strip():
                                continue
                            entries.append(json.loads(line))
                events = [e.get("payload", {}).get("event") for e in entries if isinstance(e, dict)]
                self.assertIn("key_rotation", events)
            finally:
                kernel.shutdown()


if __name__ == "__main__":
    unittest.main()
