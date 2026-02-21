import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from autocapture.storage.archive import create_archive


class VerifyArchiveCLITests(unittest.TestCase):
    def test_verify_archive_cli_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir(parents=True, exist_ok=True)
            (source / "a.txt").write_text("hello", encoding="utf-8")
            archive_path = root / "bundle.zip"
            create_archive(source, archive_path)

            repo_root = Path(__file__).resolve().parents[1]
            cmd = [
                sys.executable,
                "-m",
                "autocapture_nx",
                "verify",
                "archive",
                "--path",
                str(archive_path),
            ]
            result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("archive_verified", result.stdout)


if __name__ == "__main__":
    unittest.main()
