import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.anchor_basic.plugin import AnchorWriter
from plugins.builtin.ledger_basic.plugin import LedgerWriter


def _context(tmp: str) -> PluginContext:
    config = {
        "storage": {
            "data_dir": tmp,
            "anchor": {"path": str(Path(tmp) / "anchors.ndjson"), "use_dpapi": False},
        }
    }
    return PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)


def _verify_ledger(path: Path) -> str:
    prev_hash = None
    last_hash = None
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
            last_hash = entry_hash
    if last_hash is None:
        raise AssertionError("missing ledger entries")
    return last_hash


class LedgerAnchorGoldenTests(unittest.TestCase):
    def test_ledger_chain_and_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _context(tmp)
            ledger = LedgerWriter("ledger", ctx)
            anchor = AnchorWriter("anchor", ctx)

            last_hash = None
            for idx in range(5):
                entry = {
                    "schema_version": 1,
                    "entry_id": f"entry-{idx}",
                    "ts_utc": "2025-01-01T00:00:00Z",
                    "stage": "test",
                    "inputs": {"value": idx},
                    "outputs": {"value": idx + 1},
                    "policy_snapshot_hash": "hash",
                }
                last_hash = ledger.append(entry)
                anchor.anchor(last_hash)

            ledger_path = Path(tmp) / "ledger.ndjson"
            expected_last = _verify_ledger(ledger_path)
            self.assertEqual(expected_last, last_hash)

            anchor_path = Path(tmp) / "anchors.ndjson"
            lines = [line for line in anchor_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 5)
            last_anchor = json.loads(lines[-1])
            self.assertEqual(last_anchor["ledger_head_hash"], last_hash)


if __name__ == "__main__":
    unittest.main()
