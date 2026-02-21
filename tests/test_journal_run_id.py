import json
import tempfile
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.journal_basic.plugin import JournalWriter


class JournalRunIdTests(unittest.TestCase):
    def test_journal_includes_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = PluginContext(
                config={"storage": {"data_dir": tmp}, "runtime": {"run_id": "run1", "timezone": "UTC"}},
                get_capability=lambda _k: None,
                logger=lambda _m: None,
            )
            writer = JournalWriter("journal", ctx)
            writer.append_event("test.event", {"value": 1})
            with open(f"{tmp}/journal.ndjson", "r", encoding="utf-8") as handle:
                entry = json.loads(handle.readline())
            self.assertEqual(entry["run_id"], "run1")
            self.assertTrue(entry["event_id"].startswith("run1/"))


if __name__ == "__main__":
    unittest.main()
