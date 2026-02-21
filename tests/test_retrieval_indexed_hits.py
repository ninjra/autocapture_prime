import tempfile
import unittest
from pathlib import Path

from autocapture.indexing.lexical import LexicalIndex
from autocapture.indexing.vector import VectorIndex, LocalEmbedder
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


class RetrievalIndexedTests(unittest.TestCase):
    def test_indexed_retrieval_returns_matches_without_metadata_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lexical_path = Path(tmp) / "lexical.db"
            vector_path = Path(tmp) / "vector.db"
            lexical = LexicalIndex(lexical_path)
            vector = VectorIndex(vector_path, LocalEmbedder(None))
            store = StubStore()

            source_id = "run1/segment/0"
            derived_id = "run1/derived.text.ocr/seg0"
            store.put(
                source_id,
                {
                    "record_type": "evidence.capture.segment",
                    "ts_utc": "2026-01-24T12:00:00+00:00",
                },
            )
            store.put(
                derived_id,
                {
                    "record_type": "derived.text.ocr",
                    "ts_utc": "2026-01-24T12:00:00+00:00",
                    "text": "",
                    "source_id": source_id,
                },
            )
            lexical.index(derived_id, "needle in haystack")
            vector.index(derived_id, "needle in haystack")

            config = {
                "storage": {"lexical_path": str(lexical_path), "vector_path": str(vector_path)},
                "indexing": {"vector_backend": "sqlite"},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: store, logger=lambda _m: None)
            retrieval = RetrievalStrategy("retrieval", ctx)
            results = retrieval.search("needle", time_window=None)

            self.assertTrue(results)
            self.assertEqual(results[0]["record_id"], source_id)
            self.assertEqual(results[0]["derived_id"], derived_id)


if __name__ == "__main__":
    unittest.main()
