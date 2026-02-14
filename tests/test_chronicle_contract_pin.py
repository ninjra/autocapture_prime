from __future__ import annotations

import json
from pathlib import Path
import unittest


class ChronicleContractPinTests(unittest.TestCase):
    def test_chronicle_contracts_pinned_in_lock(self) -> None:
        root = Path(__file__).resolve().parents[1]
        lock_path = root / "contracts" / "lock.json"
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        files = payload.get("files", {})
        self.assertIsInstance(files, dict)
        self.assertIn("contracts/chronicle/v0/chronicle.proto", files)
        self.assertIn("contracts/chronicle/v0/spool_format.md", files)


if __name__ == "__main__":
    unittest.main()
