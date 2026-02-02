import base64
import struct
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.store_sqlite import StateTapeStore
from autocapture_nx.state_layer.vector_index_hnsw import HNSWStateVectorIndex


def _pack(vec):
    data = b"".join(struct.pack("e", float(v)) for v in vec)
    return {"dim": len(vec), "dtype": "f16", "blob": base64.b64encode(data).decode("ascii")}


def _evidence(ts_ms: int):
    return [
        {
            "media_id": "frame",
            "ts_start_ms": ts_ms,
            "ts_end_ms": ts_ms,
            "frame_index": 0,
            "bbox_xywh": [0, 0, 1, 1],
            "text_span": {"start": 0, "end": 0},
            "sha256": "aa",
            "redaction_applied": False,
        }
    ]


def _span(state_id: str, ts_ms: int, vec):
    return {
        "state_id": state_id,
        "session_id": "run",
        "ts_start_ms": ts_ms,
        "ts_end_ms": ts_ms + 1,
        "z_embedding": _pack(vec),
        "summary_features": {"app": "app", "window_title_hash": "hash", "top_entities": []},
        "evidence": _evidence(ts_ms),
        "provenance": {
            "producer_plugin_id": "test",
            "producer_plugin_version": "1",
            "model_id": "m",
            "model_version": "v1",
            "config_hash": "c",
            "input_artifact_ids": [],
            "created_ts_ms": ts_ms,
        },
    }


class HNSWIndexTests(unittest.TestCase):
    def test_query_hits_expected_state(self):
        ctx = PluginContext(
            config={"processing": {"state_layer": {"index": {"max_candidates": 10}}}},
            get_capability=lambda _name: None,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        index = HNSWStateVectorIndex("test.hnsw", ctx)
        spans = [
            {"state_id": "a", "session_id": "run", "ts_start_ms": 0, "ts_end_ms": 1, "z_embedding": _pack([1, 0, 0, 0]), "summary_features": {"app": ""}, "provenance": {"model_version": "v1"}},
            {"state_id": "b", "session_id": "run", "ts_start_ms": 2, "ts_end_ms": 3, "z_embedding": _pack([0, 1, 0, 0]), "summary_features": {"app": ""}, "provenance": {"model_version": "v1"}},
        ]
        index.index_spans(spans)
        hits = index.query([1, 0, 0, 0], k=1)
        self.assertEqual(hits[0].state_id, "a")

    def test_index_refreshes_on_store_change(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "state.db"
            store = StateTapeStore(db_path)
            store.insert_batch([_span("s1", 0, [1, 0, 0, 0])], [])
            ctx = PluginContext(
                config={"processing": {"state_layer": {"index": {"max_candidates": 10}}}},
                get_capability=lambda name: store if name == "storage.state_tape" else None,
                logger=lambda *_args, **_kwargs: None,
                rng=None,
                rng_seed=None,
                rng_seed_hex=None,
            )
            index = HNSWStateVectorIndex("test.hnsw", ctx)
            hits = index.query([1, 0, 0, 0], k=1)
            self.assertEqual(hits[0].state_id, "s1")

            store.insert_batch([_span("s2", 10, [0, 1, 0, 0])], [])
            hits = index.query([0, 1, 0, 0], k=1)
            self.assertEqual(hits[0].state_id, "s2")


if __name__ == "__main__":
    unittest.main()
