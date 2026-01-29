import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.clipboard_windows.plugin import ClipboardCaptureWindows


class _MemoryStore:
    def __init__(self):
        self.records = {}

    def put_new(self, record_id, value, **_kwargs):
        if record_id in self.records:
            raise FileExistsError(record_id)
        self.records[record_id] = value


class _EventBuilder:
    def __init__(self):
        self.journal = []
        self.ledger = []

    def journal_event(self, event_type, payload, **_kwargs):
        self.journal.append((event_type, payload))
        return payload.get("event_id")

    def ledger_entry(self, stage, inputs, outputs, payload=None, **_kwargs):
        self.ledger.append((stage, payload))
        return payload.get("payload_hash") if isinstance(payload, dict) else None


class ClipboardCaptureTests(unittest.TestCase):
    def test_clipboard_append_only(self):
        config = {
            "capture": {
                "clipboard": {
                    "enabled": True,
                    "max_bytes": 2000,
                    "poll_interval_s": 0.1,
                    "redact": {"enabled": False, "patterns": [], "action": "mask"},
                }
            },
            "storage": {"data_dir": "data"},
            "runtime": {},
        }
        media = _MemoryStore()
        meta = _MemoryStore()
        builder = _EventBuilder()

        def get_capability(name):
            return {
                "storage.media": media,
                "storage.metadata": meta,
                "event.builder": builder,
            }.get(name)

        plugin = ClipboardCaptureWindows(
            "builtin.tracking.clipboard.windows",
            PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None),
        )
        plugin._reader = lambda: ("hello", "text/plain")
        plugin.capture_once()
        plugin.capture_once()
        plugin._reader = lambda: ("world", "text/plain")
        plugin.capture_once()

        self.assertEqual(len(meta.records), 2)
        self.assertEqual(len(media.records), 2)
        self.assertEqual(len(builder.ledger), 2)
        for payload in meta.records.values():
            self.assertEqual(payload.get("record_type"), "evidence.clipboard.item")
            self.assertTrue(payload.get("content_hash"))
            self.assertTrue(payload.get("payload_hash"))


if __name__ == "__main__":
    unittest.main()
