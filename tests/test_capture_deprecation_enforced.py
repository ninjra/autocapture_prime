from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autocapture_nx.kernel.loader import Kernel, default_config_paths


def _check_map(kernel: Kernel) -> dict[str, object]:
    return {check.name: check for check in kernel.doctor()}


class CaptureDeprecationEnforcedTests(unittest.TestCase):
    def test_doctor_capture_plugins_deprecated_passes_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "cfg"
            data_dir = Path(tmp) / "data"
            config_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)
            (config_dir / "user.json").write_text(
                json.dumps({"storage": {"metadata_require_db": False}}, indent=2),
                encoding="utf-8",
            )
            kernel = Kernel(default_config_paths(), safe_mode=False)
            with mock.patch.object(Kernel, "_record_storage_manifest", return_value=None):
                kernel.boot(start_conductor=False)
            try:
                checks = _check_map(kernel)
                self.assertIn("capture_plugins_deprecated", checks)
                self.assertTrue(bool(checks["capture_plugins_deprecated"].ok))
            finally:
                kernel.shutdown()
                os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                os.environ.pop("AUTOCAPTURE_DATA_DIR", None)

    def test_doctor_capture_plugins_deprecated_fails_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "cfg"
            data_dir = Path(tmp) / "data"
            config_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)
            user_json = {
                "storage": {
                    "metadata_require_db": False,
                },
                "plugins": {
                    "enabled": {
                        "builtin.capture.basic": True,
                    }
                }
            }
            (config_dir / "user.json").write_text(json.dumps(user_json, indent=2), encoding="utf-8")
            kernel = Kernel(default_config_paths(), safe_mode=False)
            with mock.patch.object(Kernel, "_record_storage_manifest", return_value=None):
                kernel.boot(start_conductor=False)
            try:
                checks = _check_map(kernel)
                self.assertIn("capture_plugins_deprecated", checks)
                self.assertFalse(bool(checks["capture_plugins_deprecated"].ok))
                self.assertIn("builtin.capture.basic", str(checks["capture_plugins_deprecated"].detail))
            finally:
                kernel.shutdown()
                os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                os.environ.pop("AUTOCAPTURE_DATA_DIR", None)


if __name__ == "__main__":
    unittest.main()
