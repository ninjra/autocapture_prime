import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from autocapture.rules.ledger import RulesLedger


class RulesLedgerAppendOnlyTests(unittest.TestCase):
    def test_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RulesLedger(Path(tmp) / "rules.ndjson")
            entry = {
                "rule_id": "r1",
                "action": "add",
                "payload": {"value": 1},
                "ts_utc": datetime.now(timezone.utc).isoformat(),
            }
            ledger.append(entry)
            entries = list(ledger.iter_entries())
            self.assertEqual(len(entries), 1)
            ledger.append({**entry, "rule_id": "r2"})
            entries2 = list(ledger.iter_entries())
            self.assertEqual(len(entries2), 2)


if __name__ == "__main__":
    unittest.main()
