import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.atomic_write import atomic_write_json, atomic_write_text


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_json_produces_parseable_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "state.json"
            atomic_write_json(path, {"b": 2, "a": 1}, sort_keys=True, indent=None)
            parsed = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed, {"a": 1, "b": 2})

    def test_atomic_write_removes_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "state.json"
            atomic_write_text(path, "hello", fsync=False)
            leftovers = list(root.glob(".state.json.*.tmp"))
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()

