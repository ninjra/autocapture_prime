import unittest

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


class RetrievalTimelineTests(unittest.TestCase):
    def test_window_and_input_refs_attached(self) -> None:
        store = StubStore()
        store.put(
            "run1/segment/0",
            {
                "record_type": "evidence.capture.segment",
                "text": "needle in haystack",
                "ts_start_utc": "2026-01-24T10:00:00+00:00",
                "ts_end_utc": "2026-01-24T10:00:10+00:00",
                "ts_utc": "2026-01-24T10:00:00+00:00",
            },
        )
        store.put(
            "run1/window/0",
            {
                "record_type": "evidence.window.meta",
                "ts_utc": "2026-01-24T09:59:59+00:00",
                "window": {"title": "App A"},
            },
        )
        store.put(
            "run1/window/1",
            {
                "record_type": "evidence.window.meta",
                "ts_utc": "2026-01-24T10:00:05+00:00",
                "window": {"title": "App B"},
            },
        )
        store.put(
            "run1/input/0",
            {
                "record_type": "derived.input.summary",
                "start_ts_utc": "2026-01-24T09:59:58+00:00",
                "end_ts_utc": "2026-01-24T10:00:02+00:00",
            },
        )
        store.put(
            "run1/input/1",
            {
                "record_type": "derived.input.summary",
                "start_ts_utc": "2026-01-24T10:00:07+00:00",
                "end_ts_utc": "2026-01-24T10:00:09+00:00",
            },
        )
        ctx = PluginContext(config={}, get_capability=lambda _k: store, logger=lambda _m: None)
        retrieval = RetrievalStrategy("retrieval", ctx)
        results = retrieval.search("needle", time_window=None)
        self.assertTrue(results)
        result = results[0]
        self.assertEqual(result["window_ref"]["record_id"], "run1/window/0")
        self.assertEqual(result["window_timeline"], ["run1/window/1"])
        self.assertEqual(result["input_refs"], ["run1/input/0", "run1/input/1"])


if __name__ == "__main__":
    unittest.main()
