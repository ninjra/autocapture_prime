import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_directory


class DirectoryHashingTests(unittest.TestCase):
    def test_sha256_directory_uses_posix_relative_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.txt").write_text("b", encoding="utf-8")
            (root / "a.txt").write_text("a", encoding="utf-8")
            sub = root / "sub"
            sub.mkdir()
            (sub / "c.txt").write_text("c", encoding="utf-8")

            expected = hashlib.sha256()
            entries = []
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                entries.append((rel, path))
            for rel, path in sorted(entries, key=lambda item: item[0]):
                expected.update(rel.encode("utf-8"))
                expected.update(path.read_bytes())

            self.assertEqual(sha256_directory(root), expected.hexdigest())


if __name__ == "__main__":
    unittest.main()
