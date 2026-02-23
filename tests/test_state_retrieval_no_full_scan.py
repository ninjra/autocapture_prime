from __future__ import annotations

import unittest
from typing import Any

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.retrieval import StateRetrieval


class _Embedder:
    def embed(self, _text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class _VectorIndex:
    def query(self, _vec: list[float], *, filters: dict[str, Any], k: int) -> list[dict[str, Any]]:
        _ = filters
        _ = k
        return [{"state_id": "state_1", "score": 0.95}]


class _VectorIndexEmpty:
    def query(self, _vec: list[float], *, filters: dict[str, Any], k: int) -> list[dict[str, Any]]:
        _ = filters
        _ = k
        return []


class _Store:
    def __init__(self) -> None:
        self.get_spans_without_limit_calls = 0
        self.get_spans_by_ids_calls = 0
        self.get_spans_calls = 0

    def get_spans(
        self,
        *,
        session_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        app: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        _ = session_id
        _ = start_ms
        _ = end_ms
        _ = app
        self.get_spans_calls += 1
        if limit is None:
            self.get_spans_without_limit_calls += 1
            raise AssertionError("full_scan_forbidden")
        return [
            {
                "state_id": "state_1",
                "session_id": "run",
                "ts_start_ms": 1000,
                "ts_end_ms": 2000,
                "z_embedding": {},
                "summary_features": {"app": "terminal", "window_title_hash": "", "top_entities": []},
                "evidence": [{"media_id": "run/evidence.capture.frame/1"}],
                "provenance": {"model_version": "test-model"},
            }
        ]

    def get_spans_by_ids(self, state_ids: list[str]) -> list[dict[str, Any]]:
        self.get_spans_by_ids_calls += 1
        if "state_1" not in state_ids:
            return []
        return [
            {
                "state_id": "state_1",
                "session_id": "run",
                "ts_start_ms": 1000,
                "ts_end_ms": 2000,
                "summary_features": {"app": "terminal", "window_title_hash": "", "top_entities": []},
                "evidence": [{"media_id": "run/evidence.capture.frame/1"}],
                "provenance": {"model_version": "test-model"},
            }
        ]

    def get_edges_for_states(self, _state_ids: list[str]) -> list[dict[str, Any]]:
        return []


class StateRetrievalNoFullScanTests(unittest.TestCase):
    def test_search_uses_hit_id_lookup_without_unbounded_scan(self) -> None:
        store = _Store()
        embedder = _Embedder()
        vector_index = _VectorIndex()

        def _capability(name: str) -> Any:
            if name == "storage.state_tape":
                return store
            if name == "embedder.text":
                return embedder
            if name == "state.vector_index":
                return vector_index
            return None

        cfg = {
            "processing": {
                "state_layer": {
                    "index": {
                        "top_k": 5,
                        "min_score": 0.0,
                    }
                }
            }
        }
        ctx = PluginContext(
            config=cfg,
            get_capability=_capability,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        retrieval = StateRetrieval("state.retrieval.test", ctx)
        hits = retrieval.search("terminal")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].get("state_id"), "state_1")
        self.assertEqual(store.get_spans_without_limit_calls, 0)
        self.assertGreaterEqual(store.get_spans_by_ids_calls, 1)

    def test_linear_fallback_is_bounded(self) -> None:
        store = _Store()
        embedder = _Embedder()
        vector_index = _VectorIndexEmpty()

        def _capability(name: str) -> Any:
            if name == "storage.state_tape":
                return store
            if name == "embedder.text":
                return embedder
            if name == "state.vector_index":
                return vector_index
            return None

        cfg = {
            "processing": {
                "state_layer": {
                    "index": {
                        "top_k": 3,
                        "min_score": 0.0,
                        "max_candidates": 80,
                    }
                }
            }
        }
        ctx = PluginContext(
            config=cfg,
            get_capability=_capability,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        retrieval = StateRetrieval("state.retrieval.test.linear", ctx)
        hits = retrieval.search("work status")
        self.assertEqual(len(hits), 1)
        self.assertGreaterEqual(store.get_spans_calls, 1)
        self.assertEqual(store.get_spans_without_limit_calls, 0)


if __name__ == "__main__":
    unittest.main()
