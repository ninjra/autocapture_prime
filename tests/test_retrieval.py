import tempfile
import unittest
from pathlib import Path

from autocapture.indexing.lexical import LexicalIndex
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
        with tempfile.TemporaryDirectory() as tmp:
            lexical_path = Path(tmp) / "lexical.db"
            vector_path = Path(tmp) / "vector.db"
            lexical = LexicalIndex(lexical_path)
            store = StubStore()
            base = {
                "record_type": "evidence.capture.segment",
                "run_id": "run1",
                "segment_id": "seg",
                "ts_start_utc": "2026-01-24T10:00:00Z",
                "ts_end_utc": "2026-01-24T10:00:10Z",
                "width": 1,
                "height": 1,
                "container": {"type": "zip"},
                "content_hash": "hash",
            }
            store.put("a", {**base, "ts_utc": "2026-01-24T10:00:00Z", "text": "hello"})
            store.put("b", {**base, "ts_utc": "2026-01-24T11:00:00Z", "text": "hello"})
            lexical.index("a", "hello")
            lexical.index("b", "hello")
            config = {
                "storage": {"lexical_path": str(lexical_path), "vector_path": str(vector_path)},
                "indexing": {"vector_backend": "sqlite"},
                "retrieval": {"vector_enabled": False},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: store, logger=lambda _m: None)
            retriever = RetrievalStrategy("r", ctx)
            results = retriever.search("hello")
            self.assertEqual(results[0]["record_id"], "b")


if __name__ == "__main__":
    unittest.main()
