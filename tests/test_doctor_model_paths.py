import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.loader import Kernel


class DoctorModelPathsTests(unittest.TestCase):
    def test_doctor_reports_missing_model_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            user_path = Path(tmp) / "user.json"
            user_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "vlm_path": str(Path(tmp) / "missing_vlm"),
                            "reranker_path": str(Path(tmp) / "missing_reranker"),
                        },
                        "indexing": {"embedder_model": str(Path(tmp) / "missing_embedder")},
                    }
                ),
                encoding="utf-8",
            )
            config_dir = Path(tmp) / "config"
            data_dir = Path(tmp) / "data"
            config_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            paths = ConfigPaths(
                default_path=Path("config") / "default.json",
                user_path=user_path,
                schema_path=Path("contracts") / "config_schema.json",
                backup_dir=Path(tmp) / "backup",
            )
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)
            try:
                kernel = Kernel(paths, safe_mode=False)
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

        by_name = {check.name: check for check in checks}
        self.assertFalse(by_name["vlm_model_path"].ok)
        self.assertFalse(by_name["reranker_model_path"].ok)
        self.assertFalse(by_name["embedder_model_path"].ok)


if __name__ == "__main__":
    unittest.main()
