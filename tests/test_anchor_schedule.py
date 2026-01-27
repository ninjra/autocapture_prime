import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.event_builder import EventBuilder
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.anchor_basic.plugin import AnchorWriter


class _DummyJournal:
    def append_event(self, *args, **kwargs):
        _ = args
        _ = kwargs
        return "event"


class _DummyLedger:
    def __init__(self) -> None:
        self._seq = 0
        self._head = None

    def append(self, _entry):
        self._seq += 1
        self._head = f"hash-{self._seq}"
        return self._head

    def head_hash(self):
        return self._head


class AnchorScheduleTests(unittest.TestCase):
    def test_anchor_every_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            anchor_path = Path(tmp) / "anchors.ndjson"
            config = {
                "runtime": {"run_id": "run1"},
                "storage": {"anchor": {"path": str(anchor_path), "use_dpapi": False, "every_entries": 2, "every_minutes": 0}},
            }
            ctx = PluginContext(config=config, get_capability=lambda _n: None, logger=lambda _m: None)
            anchor = AnchorWriter("anchor", ctx)
            builder = EventBuilder(config, _DummyJournal(), _DummyLedger(), anchor)
            builder.ledger_entry("test", inputs=[], outputs=[])
            builder.ledger_entry("test", inputs=[], outputs=[])
            builder.ledger_entry("test", inputs=[], outputs=[])

            lines = [line for line in anchor_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
