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


if __name__ == "__main__":
    unittest.main()

