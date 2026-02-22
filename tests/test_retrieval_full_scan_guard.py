import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.retrieval_basic.plugin import RetrievalStrategy


class StubStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def put(self, key: str, value: dict) -> None:
        self._data[key] = value

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def keys(self):
        return list(self._data.keys())


class RetrievalFullScanGuardTests(unittest.TestCase):
    def test_full_scan_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StubStore()
            store.put(
                "run1/segment/0",
                {
                    "record_type": "evidence.capture.segment",
                    "run_id": "run1",
                    "segment_id": "seg0",
                    "ts_start_utc": "2026-01-01T00:00:00+00:00",
                    "ts_end_utc": "2026-01-01T00:00:10+00:00",
                    "width": 1,
                    "height": 1,
                    "container": {"type": "zip"},
                    "content_hash": "hash",
                    "text": "needle",
                },
            )
            config = {
                "storage": {"lexical_path": str(Path(tmp) / "lexical.db"), "vector_path": str(Path(tmp) / "vector.db")},
                "indexing": {"vector_backend": "sqlite"},
                "retrieval": {"vector_enabled": False, "latest_scan_on_miss": False},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: store, logger=lambda _m: None)
            retrieval = RetrievalStrategy("retrieval", ctx)
            results = retrieval.search("needle", time_window=None)
            self.assertEqual(results, [])
            trace = retrieval.trace()
            tiers = {entry.get("tier") for entry in trace}
            self.assertIn("FULL_SCAN_SKIPPED", tiers)


if __name__ == "__main__":
    unittest.main()
