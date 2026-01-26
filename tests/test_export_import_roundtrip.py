import tempfile
import unittest
from pathlib import Path

from autocapture.storage.archive import create_archive, verify_archive, Importer


class ExportImportRoundtripTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "a.txt").write_text("hello", encoding="utf-8")
            archive_path = Path(tmp) / "bundle.zip"
            create_archive(source, archive_path)
            ok, issues = verify_archive(archive_path)
            self.assertTrue(ok)
            self.assertEqual(issues, [])
            target = Path(tmp) / "target"
            importer = Importer(target)
            importer.import_archive(archive_path)
            self.assertEqual((target / "a.txt").read_text(encoding="utf-8"), "hello")


if __name__ == "__main__":
    unittest.main()
