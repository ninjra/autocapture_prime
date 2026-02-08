import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.loader import Kernel


class RunConfigSnapshotTests(unittest.TestCase):
    def test_effective_config_snapshot_written_to_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            default_path = root / "default.json"
            user_path = root / "user.json"
            schema_path = root / "schema.json"
            backup_dir = root / "backup"

            default = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
            schema = json.loads(Path("contracts/config_schema.json").read_text(encoding="utf-8"))
            default_path.write_text(json.dumps(default, indent=2, sort_keys=True), encoding="utf-8")
            user_path.write_text("{}", encoding="utf-8")
            schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

            paths = ConfigPaths(default_path, user_path, schema_path, backup_dir)
            kernel = Kernel(paths, safe_mode=False)
            effective = kernel.load_effective_config()
            kernel.config = effective.data
            kernel.effective_config = effective
            kernel.config.setdefault("storage", {})["data_dir"] = str(data_dir)

            info = kernel._persist_effective_config_snapshot(ts_utc="2026-02-08T00:00:00Z")
            self.assertEqual(info.get("sha256"), effective.effective_hash)
            out_path = Path(str(info.get("path")))
            self.assertTrue(out_path.exists())
            # File should parse as JSON and contain expected top-level keys.
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIn("storage", payload)


if __name__ == "__main__":
    unittest.main()

