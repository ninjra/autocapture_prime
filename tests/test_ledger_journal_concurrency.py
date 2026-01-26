import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from autocapture_nx.kernel.canonical_json import dumps
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
    config["runtime"] = {"run_id": "run1", "timezone": "UTC"}
    return PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)


def _verify_ledger(path: Path) -> None:
    prev_hash = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            entry = json.loads(line)
            entry_hash = entry.get("entry_hash")
            payload = dict(entry)
            payload.pop("entry_hash", None)
            canonical = dumps(payload)
            expected = hashlib.sha256((canonical + (prev_hash or "")).encode("utf-8")).hexdigest()
            if entry_hash != expected:
                raise AssertionError("ledger hash mismatch")
            prev_hash = entry_hash


class LedgerJournalConcurrencyTests(unittest.TestCase):
    def test_journal_concurrent_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer = JournalWriter("journal", _context(tmp))
            entries = []
            for idx in range(50):
                entries.append(
                    {
                        "schema_version": 1,
                        "event_id": f"evt-{idx}",
                        "sequence": idx,
                        "ts_utc": "2025-01-01T00:00:00Z",
                        "tzid": "UTC",
                        "offset_minutes": 0,
                        "event_type": "test",
                        "payload": {"value": idx},
                    }
                )
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(writer.append, entries))

            journal_path = Path(tmp) / "journal.ndjson"
            lines = [line for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), len(entries))
            seqs = {json.loads(line)["sequence"] for line in lines}
            self.assertEqual(seqs, {entry["sequence"] for entry in entries})

    def test_ledger_concurrent_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer = LedgerWriter("ledger", _context(tmp))
            entries = []
            for idx in range(30):
                entries.append(
                    {
                        "schema_version": 1,
                        "entry_id": f"entry-{idx}",
                        "ts_utc": "2025-01-01T00:00:00Z",
                        "stage": "test",
                        "inputs": {"value": idx},
                        "outputs": {"value": idx + 1},
                        "policy_snapshot_hash": "hash",
                    }
                )
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(writer.append, entries))

            ledger_path = Path(tmp) / "ledger.ndjson"
            lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), len(entries))
            _verify_ledger(ledger_path)


if __name__ == "__main__":
    unittest.main()
