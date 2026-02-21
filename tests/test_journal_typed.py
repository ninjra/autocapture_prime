import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.journal_basic.plugin import JournalEvent, JournalWriter


def _context(tmp: str) -> PluginContext:
    config = {
        "storage": {
            "data_dir": tmp,
            "anchor": {"path": str(Path(tmp) / "anchors.ndjson"), "use_dpapi": False},
        }
    }
    config["runtime"] = {"run_id": "run1", "timezone": "UTC"}
    return PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)


class JournalTypedTests(unittest.TestCase):
    def test_append_typed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer = JournalWriter("journal", _context(tmp))
            event = JournalEvent(
                schema_version=1,
                event_id="evt-1",
                sequence=0,
                ts_utc="2025-01-01T00:00:00Z",
                tzid="UTC",
                offset_minutes=0,
                event_type="typed",
                payload={"value": 1},
            )
            writer.append_typed(event)
            path = Path(tmp) / "journal.ndjson"
            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(entries[0]["event_type"], "typed")


if __name__ == "__main__":
    unittest.main()
