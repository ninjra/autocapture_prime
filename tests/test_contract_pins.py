import json
import unittest
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_file


class ContractPinTests(unittest.TestCase):
    def test_contract_hashes_match_lock(self):
        lock_path = Path("contracts/lock.json")
        self.assertTrue(lock_path.exists(), "contracts/lock.json missing")
        with lock_path.open("r", encoding="utf-8") as handle:
            lock = json.load(handle)
        for rel, expected in lock.get("files", {}).items():
            self.assertEqual(sha256_file(rel), expected, f"hash mismatch for {rel}")


if __name__ == "__main__":
    unittest.main()
