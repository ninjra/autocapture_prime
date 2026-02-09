import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.operator_ledger import record_operator_action


class OperatorCommandsLedgeredTests(unittest.TestCase):
    def test_operator_actions_write_journal_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            cfg = {
                "storage": {"data_dir": str(data_dir)},
                "runtime": {"run_id": "test_run", "timezone": "UTC"},
            }
            result = record_operator_action(config=cfg, action="reindex", payload={"scheduled": True})
            self.assertTrue(result.get("ok"), result)
            self.assertTrue((data_dir / "journal.ndjson").exists())
            self.assertTrue((data_dir / "ledger.ndjson").exists())

            journal_lines = (data_dir / "journal.ndjson").read_text(encoding="utf-8").splitlines()
            self.assertTrue(journal_lines)
            journal = json.loads(journal_lines[-1])
            self.assertEqual(journal.get("event_type"), "operator.reindex")

            ledger_lines = (data_dir / "ledger.ndjson").read_text(encoding="utf-8").splitlines()
            self.assertTrue(ledger_lines)
            ledger = json.loads(ledger_lines[-1])
            self.assertEqual(ledger.get("record_type"), "operator.reindex")


if __name__ == "__main__":
    unittest.main()

