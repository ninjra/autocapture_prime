import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
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
    data_dir = root / "data"
    user_override = {
        "paths": {
            "config_dir": str(root),
            "data_dir": str(data_dir),
        },
        "runtime": {"run_id": "run1", "timezone": "UTC"},
        "storage": {
            "data_dir": str(data_dir),
            "spool_dir": str(data_dir / "spool"),
            "crypto": {
                "keyring_path": str(data_dir / "vault" / "keyring.json"),
                "root_key_path": str(data_dir / "vault" / "root.key"),
            },
        },
        "kernel": {
            "crash_loop": {
                "enabled": True,
                "max_crashes": 1,
                "window_s": 3600,
                "min_runtime_s": 0,
                "cooldown_s": 0,
                "reset_on_clean_shutdown": True,
            }
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
        json.dump(user_override, handle, indent=2, sort_keys=True)
    return ConfigPaths(default_path, user_path, schema_path, backup_dir)


class CrashLoopSafeModeTests(unittest.TestCase):
    def test_crash_loop_forces_safe_mode(self) -> None:
        try:
            import sqlcipher3  # noqa: F401
        except Exception:
            self.skipTest("sqlcipher3 not available")
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            data_dir = Path(tmp) / "data"
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)
            try:
                paths = _paths(tmp)
                data_dir.mkdir(parents=True, exist_ok=True)
                run_state = {
                    "run_id": "run0",
                    "state": "running",
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
                (data_dir / "run_state.json").write_text(json.dumps(run_state), encoding="utf-8")

                kernel = Kernel(paths, safe_mode=False)
                system = kernel.boot(start_conductor=False)
                _ = system
                try:
                    self.assertTrue(kernel.safe_mode)
                    self.assertEqual(kernel.safe_mode_reason, "crash_loop")
                    self.assertFalse(kernel.config["processing"]["idle"]["enabled"])
                    crash_status = kernel.crash_loop_status()
                    self.assertIsInstance(crash_status, dict)
                    self.assertGreaterEqual(int(crash_status.get("crash_count", 0)), 1)
                finally:
                    kernel.shutdown()
            finally:
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data


if __name__ == "__main__":
    unittest.main()
