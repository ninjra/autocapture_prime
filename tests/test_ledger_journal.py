import tempfile
import unittest
import json

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.ledger_basic.plugin import LedgerWriter
from plugins.builtin.journal_basic.plugin import JournalWriter


class LedgerJournalTests(unittest.TestCase):
    def test_ledger_requires_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = PluginContext(config={"storage": {"data_dir": tmp}}, get_capability=lambda _k: None, logger=lambda _m: None)
            ledger = LedgerWriter("ledger", ctx)
            with self.assertRaises(ValueError):
                ledger.append({"schema_version": 1})

    def test_journal_requires_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = PluginContext(config={"storage": {"data_dir": tmp}}, get_capability=lambda _k: None, logger=lambda _m: None)
            journal = JournalWriter("journal", ctx)
            with self.assertRaises(ValueError):
                journal.append({"schema_version": 1})

    def test_ledger_hash_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = PluginContext(config={"storage": {"data_dir": tmp}}, get_capability=lambda _k: None, logger=lambda _m: None)
            ledger = LedgerWriter("ledger", ctx)
            entry1 = {
                "schema_version": 1,
                "entry_id": "e1",
                "ts_utc": "2025-01-01T00:00:00Z",
                "stage": "capture",
                "inputs": [],
                "outputs": ["e1"],
                "policy_snapshot_hash": "hash",
            }
            h1 = ledger.append(entry1)
            entry2 = {
                "schema_version": 1,
                "entry_id": "e2",
                "ts_utc": "2025-01-01T00:00:01Z",
                "stage": "capture",
                "inputs": ["e1"],
                "outputs": ["e2"],
                "policy_snapshot_hash": "hash",
            }
            h2 = ledger.append(entry2)
            self.assertNotEqual(h1, h2)
            with open(f"{tmp}/ledger.ndjson", "r", encoding="utf-8") as handle:
                lines = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual(lines[0]["entry_hash"], h1)
            self.assertEqual(lines[1]["prev_hash"], h1)


if __name__ == "__main__":
    unittest.main()
