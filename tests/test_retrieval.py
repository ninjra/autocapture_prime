import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.retrieval_basic.plugin import RetrievalStrategy


class StubStore:
    def __init__(self):
        self._data = {}

    def put(self, key, value):
        self._data[key] = value

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return list(self._data.keys())


class RetrievalTests(unittest.TestCase):
    def test_tie_break(self):
        store = StubStore()
        store.put("a", {"text": "hello", "ts_utc": "2026-01-24T10:00:00Z"})
        store.put("b", {"text": "hello", "ts_utc": "2026-01-24T11:00:00Z"})
        ctx = PluginContext(config={}, get_capability=lambda _k: store, logger=lambda _m: None)
        retriever = RetrievalStrategy("r", ctx)
        results = retriever.search("hello")
        self.assertEqual(results[0]["record_id"], "b")


if __name__ == "__main__":
    unittest.main()
