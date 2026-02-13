import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
from autocapture_nx.kernel.loader import Kernel, default_config_paths


class PlatformPathTests(unittest.TestCase):
    def test_env_overrides_apply_to_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            data_dir = Path(tmp) / "data"
            config_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)

            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)
            try:
                paths = ConfigPaths(
                    default_path=Path("config") / "default.json",
                    user_path=Path(tmp) / "user.json",
                    schema_path=Path("contracts") / "config_schema.json",
                    backup_dir=Path(tmp) / "backup",
                )
                config = load_config(paths, safe_mode=True)
            finally:
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data

        self.assertEqual(Path(config["paths"]["config_dir"]).resolve(), config_dir.resolve())
        self.assertEqual(Path(config["paths"]["data_dir"]).resolve(), data_dir.resolve())
        storage = config["storage"]
        self.assertEqual(Path(storage["data_dir"]).resolve(), data_dir.resolve())
        self.assertTrue(Path(storage["media_dir"]).resolve().is_relative_to(data_dir.resolve()))
        self.assertTrue(Path(storage["spool_dir"]).resolve().is_relative_to(data_dir.resolve()))
        anchor_path = Path(storage["anchor"]["path"]).resolve()
        # Anchors are run-scoped but intentionally stored outside data_dir to keep a
        # cleaner integrity boundary (see doctor check anchor_separate_domain).
        self.assertFalse(anchor_path.is_relative_to(data_dir.resolve()))
        self.assertTrue(anchor_path.is_relative_to(data_dir.resolve().parent))

    def test_doctor_reports_path_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            data_dir = Path(tmp) / "data"
            config_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)

            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)
            try:
                kernel = Kernel(default_config_paths(), safe_mode=True)
                kernel.boot()
                checks = kernel.doctor()
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

        names = {check.name for check in checks}
        self.assertIn("config_dir_writable", names)
        self.assertIn("data_dir_writable", names)


if __name__ == "__main__":
    unittest.main()
