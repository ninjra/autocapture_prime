import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from autocapture.pillars.citable import Ledger, verify_ledger


class ProvenanceChainTests(unittest.TestCase):
    def test_ledger_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.ndjson"
            ledger = Ledger(path)
            entry = {
                "schema_version": 1,
                "entry_id": "e1",
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "stage": "capture",
                "inputs": [],
                "outputs": [],
                "policy_snapshot_hash": "abc",
            }
            ledger.append(entry)
            entry2 = dict(entry)
            entry2["entry_id"] = "e2"
            ledger.append(entry2)
            ok, errors = verify_ledger(path)
            self.assertTrue(ok)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
