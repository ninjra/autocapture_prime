import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_directory


def _write_files(root: Path, names: list[str]) -> None:
    for name in names:
        path = root / name
        path.write_text(f"payload:{name}", encoding="utf-8")


class HashingDeterminismTests(unittest.TestCase):
    def test_directory_hash_independent_of_creation_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            root1 = Path(tmp1)
            root2 = Path(tmp2)
            _write_files(root1, ["b.txt", "a.txt", "c.txt"])
            _write_files(root2, ["c.txt", "b.txt", "a.txt"])
            digest1 = sha256_directory(root1)
            digest2 = sha256_directory(root2)
            self.assertEqual(digest1, digest2)


if __name__ == "__main__":
    unittest.main()
