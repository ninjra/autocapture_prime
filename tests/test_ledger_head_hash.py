import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
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


class LedgerHeadHashTests(unittest.TestCase):
    def test_head_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer = LedgerWriter("ledger", _context(tmp))
            entry = {
                "record_type": "ledger.entry",
                "schema_version": 1,
                "entry_id": "entry-1",
                "ts_utc": "2025-01-01T00:00:00Z",
                "stage": "test",
                "inputs": [],
                "outputs": [],
                "policy_snapshot_hash": "hash",
            }
            writer.append(entry)
            head = writer.head_hash()
            self.assertIsNotNone(head)
            path = Path(tmp) / "ledger.ndjson"
            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(entries[-1]["entry_hash"], head)

    def test_loads_last_hash_from_existing_log_without_full_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.ndjson"
            path.write_text("", encoding="utf-8")
            for idx in range(200):
                payload = {
                    "record_type": "ledger.entry",
                    "schema_version": 1,
                    "entry_id": f"entry-{idx}",
                    "ts_utc": "2025-01-01T00:00:00Z",
                    "stage": "test",
                    "inputs": [],
                    "outputs": [],
                    "policy_snapshot_hash": "hash",
                    "entry_hash": f"h{idx:03d}",
                }
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload) + "\n")
            writer = LedgerWriter("ledger", _context(tmp))
            self.assertEqual(writer.head_hash(), "h199")

    def test_loads_hash_for_legacy_prefixed_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.ndjson"
            legacy_payload = '{"entry_id":"legacy-1","entry_hash":"legacy_hash"}'
            path.write_text(f"abc123 {legacy_payload}\n", encoding="utf-8")
            writer = LedgerWriter("ledger", _context(tmp))
            expected = hashlib.sha256(legacy_payload.encode("utf-8")).hexdigest()
            self.assertEqual(writer.head_hash(), expected)


if __name__ == "__main__":
    unittest.main()
