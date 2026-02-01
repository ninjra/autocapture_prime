import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.loader import Kernel, default_config_paths


class DoctorAnchorBoundaryTests(unittest.TestCase):
    def test_anchor_boundary_detects_inside_data_dir(self) -> None:
        original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
        original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            data_dir = Path(tmp) / "data"
            config_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)
            anchor_path = data_dir / "anchors" / "anchors.ndjson"
            user_cfg = {
                "storage": {
                    "data_dir": str(data_dir),
                    "anchor": {"path": str(anchor_path), "use_dpapi": False, "sign": False},
                },
                "plugins": {
                    "allowlist": [
                        "builtin.storage.memory",
                        "builtin.journal.basic",
                        "builtin.ledger.basic",
                        "builtin.anchor.basic",
                    ],
                    "locks": {"enforce": False},
                },
            }
            (config_dir / "user.json").write_text(json.dumps(user_cfg, indent=2, sort_keys=True), encoding="utf-8")
            kernel = Kernel(default_config_paths(), safe_mode=False)
            kernel.boot(start_conductor=False)
            try:
                checks = kernel.doctor()
                check_map = {check.name: check for check in checks}
                self.assertIn("anchor_separate_domain", check_map)
                self.assertFalse(check_map["anchor_separate_domain"].ok)
            finally:
                kernel.shutdown()
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
