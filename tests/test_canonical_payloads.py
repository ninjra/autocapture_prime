import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.canonical_json import CanonicalJSONError
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.journal_basic.plugin import JournalWriter
from plugins.builtin.ledger_basic.plugin import LedgerWriter


def _context(tmp: str) -> PluginContext:
    config = {
        "storage": {
            "data_dir": tmp,
            "anchor": {"path": str(Path(tmp) / "anchors.ndjson"), "use_dpapi": False},
        }
    }
    return PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)


class CanonicalPayloadTests(unittest.TestCase):
    def test_journal_rejects_float(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer = JournalWriter("journal", _context(tmp))
            entry = {
                "schema_version": 1,
                "event_id": "evt-1",
                "sequence": 1,
                "ts_utc": "2025-01-01T00:00:00Z",
                "tzid": "UTC",
                "offset_minutes": 0,
                "event_type": "test",
                "payload": {"value": 1},
            }
            writer.append(entry)
            bad_entry = dict(entry)
            bad_entry["payload"] = {"value": 1.5}
            with self.assertRaises(CanonicalJSONError):
                writer.append(bad_entry)

    def test_ledger_rejects_float(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer = LedgerWriter("ledger", _context(tmp))
            entry = {
                "schema_version": 1,
                "entry_id": "entry-1",
                "ts_utc": "2025-01-01T00:00:00Z",
                "stage": "test",
                "inputs": {"value": 1},
                "outputs": {"value": 2},
                "policy_snapshot_hash": "hash",
            }
            writer.append(entry)
            bad_entry = dict(entry)
            bad_entry["inputs"] = {"value": 1.5}
            with self.assertRaises(CanonicalJSONError):
                writer.append(bad_entry)


if __name__ == "__main__":
    unittest.main()
