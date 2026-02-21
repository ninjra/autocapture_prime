import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.file_activity_windows.plugin import FileActivityWindows, _FileState


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


class FileActivityCaptureTests(unittest.TestCase):
    def test_file_activity_events(self):
        config = {
            "capture": {
                "file_activity": {
                    "enabled": True,
                    "poll_interval_s": 1.0,
                    "roots": [],
                    "include_patterns": [],
                    "exclude_patterns": [],
                    "max_files": 100,
                    "max_events_per_scan": 10,
                }
            },
            "storage": {"data_dir": "data"},
            "runtime": {},
        }
        meta = _MemoryStore()
        builder = _EventBuilder()

        def get_capability(name):
            return {
                "storage.metadata": meta,
                "event.builder": builder,
            }.get(name)

        plugin = FileActivityWindows(
            "builtin.tracking.file_activity.windows",
            PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None),
        )
        snapshot1 = {"C:/tmp/a.txt": _FileState(mtime=1.0, size=10)}
        snapshot2 = {
            "C:/tmp/a.txt": _FileState(mtime=2.0, size=12),
            "C:/tmp/b.txt": _FileState(mtime=1.0, size=5),
        }
        plugin._scan = lambda: snapshot1
        plugin.capture_once()
        plugin._scan = lambda: snapshot2
        plugin.capture_once()

        self.assertEqual(len(meta.records), 3)
        operations = {record.get("operation") for record in meta.records.values()}
        self.assertIn("created", operations)
        self.assertIn("modified", operations)
        for payload in meta.records.values():
            self.assertEqual(payload.get("record_type"), "evidence.file.activity")
            self.assertTrue(payload.get("payload_hash"))


if __name__ == "__main__":
    unittest.main()
