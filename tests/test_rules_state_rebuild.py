import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from autocapture.rules.ledger import RulesLedger
from autocapture.rules.store import RulesStore


class RulesStateRebuildTests(unittest.TestCase):
    def test_state_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RulesLedger(Path(tmp) / "rules.ndjson")
            now = datetime.now(timezone.utc).isoformat()
            ledger.append({"rule_id": "r1", "action": "add", "payload": {"value": 1}, "ts_utc": now})
            ledger.append({"rule_id": "r1", "action": "update", "payload": {"value": 2}, "ts_utc": now})
            store = RulesStore(ledger)
            state = store.rebuild_state()
            self.assertEqual(state["r1"]["value"], 2)


if __name__ == "__main__":
    unittest.main()
