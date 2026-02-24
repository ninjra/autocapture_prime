import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.instance_lock import acquire_instance_lock
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
        "runtime": {"run_id": "run_fast_boot", "timezone": "UTC"},
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
            # Keep boot lightweight; most gates already cover full plugin matrix.
            "enabled": {
                "builtin.capture.windows": False,
                "builtin.capture.audio.windows": False,
                "builtin.capture.screenshot.windows": False,
                "builtin.tracking.input.windows": False,
                "builtin.window.metadata.windows": False,
            }
        },
        "web": {"allow_remote": False, "bind_host": "127.0.0.1"},
    }
    with open(user_path, "w", encoding="utf-8") as handle:
        json.dump(user_override, handle, indent=2, sort_keys=True)
    return ConfigPaths(default_path, user_path, schema_path, backup_dir)


class _KernelProbe(Kernel):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.called: list[str] = []

    def _record_storage_manifest(self, *args, **kwargs) -> None:  # type: ignore[override]
        self.called.append("record_storage_manifest")
        return super()._record_storage_manifest(*args, **kwargs)

    def _run_recovery(self, *args, **kwargs) -> None:  # type: ignore[override]
        self.called.append("run_recovery")
        return super()._run_recovery(*args, **kwargs)

    def _run_integrity_sweep(self, *args, **kwargs) -> None:  # type: ignore[override]
        self.called.append("run_integrity_sweep")
        return super()._run_integrity_sweep(*args, **kwargs)


class KernelFastBootOverrideTests(unittest.TestCase):
    def test_fast_boot_true_skips_heavy_boot_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            kernel = _KernelProbe(paths, safe_mode=False)
            kernel.boot(start_conductor=False, fast_boot=True)
            kernel.shutdown()
            self.assertNotIn("record_storage_manifest", kernel.called)
            self.assertNotIn("run_recovery", kernel.called)
            self.assertNotIn("run_integrity_sweep", kernel.called)

    def test_fast_boot_false_runs_heavy_boot_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            kernel = _KernelProbe(paths, safe_mode=False)
            kernel.boot(start_conductor=False, fast_boot=False)
            kernel.shutdown()
            self.assertIn("record_storage_manifest", kernel.called)
            self.assertIn("run_recovery", kernel.called)
            self.assertIn("run_integrity_sweep", kernel.called)

    def test_boot_with_readonly_metadata_db_keeps_storage_capability(self) -> None:
        if os.name == "nt":
            self.skipTest("readonly chmod semantics differ on Windows")
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            data_dir = Path(tmp) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "metadata.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE metadata (id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_type TEXT, ts_utc TEXT, run_id TEXT)"
            )
            conn.execute(
                "CREATE TABLE entity_map (token TEXT PRIMARY KEY, value TEXT, kind TEXT, key_id TEXT, key_version INTEGER, first_seen_ts TEXT)"
            )
            conn.execute(
                "INSERT INTO metadata (id, payload, record_type, ts_utc, run_id) VALUES (?, ?, ?, ?, ?)",
                ("run1/derived.test/1", "{\"v\":1}", "derived.test", "2026-02-24T00:00:00Z", "run1"),
            )
            conn.commit()
            conn.close()
            os.chmod(db_path, 0o444)

            kernel = Kernel(paths, safe_mode=False)
            system = kernel.boot(start_conductor=False, fast_boot=True)
            try:
                self.assertTrue(system.has("storage.metadata"))
                store = system.get("storage.metadata")
                rows = store.latest("derived.test", limit=1)
                self.assertIsInstance(rows, list)
            finally:
                kernel.shutdown()

    def test_manifest_write_readonly_error_is_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            kernel = Kernel(paths, safe_mode=False)
            with (
                patch.dict(os.environ, {"AUTOCAPTURE_QUERY_METADATA_ONLY": "0"}, clear=False),
                patch.object(Kernel, "_record_storage_manifest", side_effect=PermissionError("readonly manifest write denied")),
            ):
                system = kernel.boot(start_conductor=False, fast_boot=False)
                self.assertIsNotNone(system)
                self.assertTrue(system.has("event.builder"))
            kernel.shutdown()

    def test_shutdown_releases_instance_lock_after_partial_boot_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            kernel = Kernel(paths, safe_mode=False)
            with patch.object(Kernel, "_record_storage_manifest", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    kernel.boot(start_conductor=False, fast_boot=False)
            kernel.shutdown()
            lock = acquire_instance_lock(Path(tmp) / "data")
            lock.close()


if __name__ == "__main__":
    unittest.main()
