import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.windows.acl import harden_path_permissions


class ACLHardeningTests(unittest.TestCase):
    def test_posix_permissions(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX-only permissions check")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret.txt"
            path.write_text("secret", encoding="utf-8")
            harden_path_permissions(path, is_dir=False)
            mode = path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_posix_dir_permissions(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX-only permissions check")
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp) / "vault"
            dir_path.mkdir(parents=True, exist_ok=True)
            harden_path_permissions(dir_path, is_dir=True)
            mode = dir_path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o700)


if __name__ == "__main__":
    unittest.main()
