import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_directory


class HashingSymlinkTests(unittest.TestCase):
    def test_symlink_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "file.txt"
            target.write_text("data", encoding="utf-8")
            link = root / "link.txt"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink not supported")
            with self.assertRaises(ValueError):
                sha256_directory(root)


if __name__ == "__main__":
    unittest.main()
