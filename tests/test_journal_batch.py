import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.journal_basic.plugin import JournalWriter


class JournalBatchTests(unittest.TestCase):
    def test_append_batch_assigns_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = PluginContext(
                config={"storage": {"data_dir": tmp}, "runtime": {"run_id": "run1", "timezone": "UTC"}},
                get_capability=lambda _k: None,
                logger=lambda _m: None,
            )
            writer = JournalWriter("journal", ctx)
            entries = [
                {
                    "schema_version": 1,
                    "event_id": None,
                    "sequence": None,
                    "ts_utc": None,
                    "tzid": None,
                    "offset_minutes": 0,
                    "event_type": "input.batch",
                    "payload": {"events": []},
                    "run_id": "run1",
                },
                {
                    "schema_version": 1,
                    "event_id": None,
                    "sequence": None,
                    "ts_utc": None,
                    "tzid": None,
                    "offset_minutes": 0,
                    "event_type": "input.batch",
                    "payload": {"events": []},
                    "run_id": "run1",
                },
            ]
            ids = writer.append_batch(entries)
            self.assertEqual(len(ids), 2)
            path = Path(tmp) / "journal.ndjson"
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(lines[0]["sequence"], 0)
            self.assertEqual(lines[1]["sequence"], 1)
            self.assertTrue(lines[0]["event_id"].startswith("run1/"))
            self.assertTrue(lines[1]["event_id"].startswith("run1/"))


if __name__ == "__main__":
    unittest.main()
