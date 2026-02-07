import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.errors import ConfigError
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
        "runtime": {"run_id": "run_lock", "timezone": "UTC"},
        "storage": {
            "data_dir": str(root / "data"),
            "spool_dir": str(root / "data" / "spool"),
            "no_deletion_mode": True,
            "raw_first_local": True,
            "crypto": {
                "keyring_path": str(root / "data" / "vault" / "keyring.json"),
                "root_key_path": str(root / "data" / "vault" / "root.key"),
            },
        },
        "plugins": {
            # Keep this test lightweight and deterministic: use in-memory storage
            # to avoid SQLCipher keying/IO variability in ephemeral temp dirs.
            "safe_mode": True,
            "default_pack": [
                "builtin.anchor.basic",
                "builtin.answer.basic",
                "builtin.backpressure.basic",
                "builtin.capture.basic",
                "builtin.citation.basic",
                "builtin.journal.basic",
                "builtin.ledger.basic",
                "builtin.observability.basic",
                "builtin.time.basic",
                "builtin.storage.memory",
            ],
            "enabled": {
                "builtin.capture.windows": False,
                "builtin.capture.audio.windows": False,
                "builtin.tracking.input.windows": False,
                "builtin.window.metadata.windows": False,
                "builtin.storage.sqlcipher": False,
                "builtin.storage.encrypted": False,
            }
        },
        "web": {"allow_remote": False, "bind_host": "127.0.0.1"},
    }
    with open(user_path, "w", encoding="utf-8") as handle:
        json.dump(user_override, handle, indent=2, sort_keys=True)
    return ConfigPaths(default_path, user_path, schema_path, backup_dir)


class InstanceLockTests(unittest.TestCase):
    def test_instance_lock_blocks_concurrent_boot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            k1 = Kernel(paths, safe_mode=False)
            k1.boot(start_conductor=False, fast_boot=True)
            try:
                k2 = Kernel(paths, safe_mode=False)
                with self.assertRaises(ConfigError):
                    k2.boot(start_conductor=False, fast_boot=True)
            finally:
                k1.shutdown()


if __name__ == "__main__":
    unittest.main()
