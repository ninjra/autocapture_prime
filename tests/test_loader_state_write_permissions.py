import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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


class LoaderStateWritePermissionTests(unittest.TestCase):
    def test_crash_history_permission_error_does_not_abort(self) -> None:
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
                with patch.object(kernel, "_write_crash_history", side_effect=PermissionError("denied")):
                    status = kernel._evaluate_crash_loop(kernel.config)  # pylint: disable=protected-access
                    self.assertTrue(status.enabled)
            finally:
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data

    def test_run_state_permission_error_does_not_abort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            kernel = Kernel(paths, safe_mode=False)
            with patch("autocapture_nx.kernel.loader.write_run_state", side_effect=PermissionError("denied")):
                kernel._write_run_state("run-x", "running")  # pylint: disable=protected-access

    def test_effective_config_snapshot_permission_error_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            kernel = Kernel(paths, safe_mode=False)
            kernel.effective_config = kernel.load_effective_config()
            kernel.config = dict(kernel.effective_config.data)
            with patch("autocapture_nx.kernel.loader.atomic_write_text", side_effect=PermissionError("denied")):
                snapshot = kernel._persist_effective_config_snapshot(ts_utc="2026-02-11T00:00:00Z")  # pylint: disable=protected-access
            self.assertEqual(snapshot, {})


if __name__ == "__main__":
    unittest.main()
