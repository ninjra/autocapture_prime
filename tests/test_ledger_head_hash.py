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


if __name__ == "__main__":
    unittest.main()
