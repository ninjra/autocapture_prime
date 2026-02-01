import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from autocapture.storage.migrate import migrate_data_dir


class StorageMigrationTests(unittest.TestCase):
    def test_migrate_data_dir_fixture(self) -> None:
        fixture_root = Path("tests/fixtures/migrations/v1/data_dir")
        manifest = json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))
        expected_files = manifest.get("files", {})
        manifest_size = (fixture_root / "manifest.json").stat().st_size
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "data"
            result = migrate_data_dir(str(fixture_root), str(dst), dry_run=False, verify=True)
            expected_total_files = int(manifest.get("total_files", 0)) + 1
            expected_total_bytes = int(manifest.get("total_bytes", 0)) + manifest_size
            self.assertEqual(result.files, expected_total_files)
            self.assertEqual(result.bytes, expected_total_bytes)
            self.assertEqual(result.verified, expected_total_files)
            for rel, expected_hash in expected_files.items():
                data = (dst / rel).read_bytes()
                actual = hashlib.sha256(data).hexdigest()
                self.assertEqual(actual, expected_hash)


if __name__ == "__main__":
    unittest.main()
