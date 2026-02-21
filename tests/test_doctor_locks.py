import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autocapture_nx.kernel.loader import Kernel, default_config_paths


class DoctorLocksTests(unittest.TestCase):
    def test_doctor_detects_contract_lock_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            kernel = Kernel(default_config_paths(), safe_mode=False)
            kernel.boot(start_conductor=False)
            try:
                original_lock = Path("contracts") / "lock.json"
                lock_copy = Path(tmp) / "lock.json"
                lock_copy.write_text(original_lock.read_text(encoding="utf-8"), encoding="utf-8")
                data = json.loads(lock_copy.read_text(encoding="utf-8"))
                files = data.get("files", {})
                if files:
                    first_key = sorted(files.keys())[0]
                    files[first_key] = "deadbeef"
                lock_copy.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

                from autocapture_nx.kernel import loader as loader_mod

                original_resolve = loader_mod.resolve_repo_path

                def _patched(path: str | Path):
                    if str(path) == "contracts/lock.json":
                        return lock_copy
                    return original_resolve(path)

                with mock.patch.object(loader_mod, "resolve_repo_path", side_effect=_patched):
                    checks = kernel.doctor()
                lock_checks = {c.name: c for c in checks}
                self.assertIn("contracts_lock", lock_checks)
                self.assertFalse(lock_checks["contracts_lock"].ok)
            finally:
                kernel.shutdown()
                os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                os.environ.pop("AUTOCAPTURE_DATA_DIR", None)

    def test_doctor_detects_plugin_lock_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            data_dir = Path(tmp) / "data"
            config_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)

            lock_src = Path("config") / "plugin_locks.json"
            lock_copy = config_dir / "plugin_locks.json"
            lock_copy.write_text(lock_src.read_text(encoding="utf-8"), encoding="utf-8")

            user_cfg = {
                "plugins": {"locks": {"lockfile": str(lock_copy)}},
            }
            (config_dir / "user.json").write_text(json.dumps(user_cfg, indent=2), encoding="utf-8")

            kernel = Kernel(default_config_paths(), safe_mode=False)
            kernel.boot(start_conductor=False)
            try:
                data = json.loads(lock_copy.read_text(encoding="utf-8"))
                plugins = data.get("plugins", {})
                if plugins:
                    first_key = sorted(plugins.keys())[0]
                    plugins[first_key]["artifact_sha256"] = "deadbeef"
                lock_copy.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

                checks = kernel.doctor()
                lock_checks = {c.name: c for c in checks}
                self.assertIn("plugin_locks", lock_checks)
                self.assertFalse(lock_checks["plugin_locks"].ok)
            finally:
                kernel.shutdown()
                os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                os.environ.pop("AUTOCAPTURE_DATA_DIR", None)


if __name__ == "__main__":
    unittest.main()
