import tempfile
import unittest
from pathlib import Path
import zipfile

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

    def test_verify_rejects_unsafe_manifest_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("../evil.txt", "bad")
                zf.writestr("manifest.json", '{"schema_version":1,"files":{"../evil.txt":"deadbeef"}}')
            ok, issues = verify_archive(archive_path)
            self.assertFalse(ok)
            self.assertIn("unsafe_member:../evil.txt", issues)

    def test_import_rejects_zip_slip_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "unsafe_import.zip"
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "a.txt").write_text("hello", encoding="utf-8")
            create_archive(source, archive_path)
            with zipfile.ZipFile(archive_path, "a", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("../evil.txt", "bad")
            target = Path(tmp) / "target"
            importer = Importer(target)
            with self.assertRaisesRegex(ValueError, "unsafe_zip_member"):
                importer.import_archive(archive_path)


if __name__ == "__main__":
    unittest.main()
