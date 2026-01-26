import tempfile
import unittest
from pathlib import Path

from autocapture.storage.migrate import migrate_data_dir


class StorageMigrateTests(unittest.TestCase):
    def test_migrate_copies_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            (src_path / "metadata").mkdir(parents=True, exist_ok=True)
            sample = src_path / "metadata" / "file.txt"
            sample.write_text("payload", encoding="utf-8")

            result = migrate_data_dir(src, dst, dry_run=False, verify=True)
            self.assertEqual(result.files, 1)
            self.assertEqual(result.verified, 1)
            self.assertTrue((Path(dst) / "metadata" / "file.txt").exists())
            self.assertTrue(sample.exists())

    def test_migrate_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            (src_path / "media").mkdir(parents=True, exist_ok=True)
            sample = src_path / "media" / "file.bin"
            sample.write_bytes(b"payload")

            result = migrate_data_dir(src, dst, dry_run=True, verify=True)
            self.assertEqual(result.files, 1)
            self.assertEqual(result.verified, 0)
            self.assertFalse((Path(dst) / "media" / "file.bin").exists())


if __name__ == "__main__":
    unittest.main()
