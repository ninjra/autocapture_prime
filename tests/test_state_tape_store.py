import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.builder_jepa import JEPAStateBuilder
from autocapture_nx.state_layer.store_sqlite import StateTapeStore


def _state_record(ts_ms: int, frame_id: str) -> dict:
    return {
        "record_type": "derived.sst.state",
        "artifact_id": f"run/derived.sst.state/{frame_id}",
        "screen_state": {
            "state_id": f"state_{frame_id}",
            "frame_id": frame_id,
            "frame_index": 0,
            "ts_ms": ts_ms,
            "phash": "abcd" * 16,
            "image_sha256": "ff" * 32,
            "width": 320,
            "height": 180,
            "tokens": [],
            "visible_apps": ["app"],
            "element_graph": {"elements": [], "edges": []},
            "text_blocks": [],
            "tables": [],
            "spreadsheets": [],
            "code_blocks": [],
            "charts": [],
        },
    }


class StateTapeStoreTests(unittest.TestCase):
    def _builder(self) -> JEPAStateBuilder:
        config = {
            "processing": {
                "state_layer": {
                    "windowing_mode": "fixed_duration",
                    "window_ms": 5000,
                    "max_evidence_refs": 3,
                    "builder": {
                        "text_weight": 1.0,
                        "vision_weight": 0.6,
                        "layout_weight": 0.4,
                        "input_weight": 0.2,
                    },
                }
            }
        }
        ctx = PluginContext(
            config=config,
            get_capability=lambda _name: None,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        return JEPAStateBuilder("test.state.builder", ctx)

    def test_state_tape_append_only(self):
        builder = self._builder()
        states = [_state_record(1000, "frame1"), _state_record(2000, "frame2")]
        batch = {"session_id": "run", "states": states}
        out = builder.process(batch)
        spans = out["spans"]
        edges = out["edges"]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state_tape.db"
            store = StateTapeStore(path)
            counts = store.insert_batch(spans, edges)
            self.assertEqual(counts.spans_inserted, len(spans))
            self.assertEqual(counts.edges_inserted, len(edges))
            counts2 = store.insert_batch(spans, edges)
            self.assertEqual(counts2.spans_inserted, 0)
            self.assertEqual(counts2.edges_inserted, 0)
            fetched = store.get_spans()
            self.assertTrue(fetched)
            self.assertTrue(fetched[0].get("evidence"))

    def test_state_tape_accepts_dataclass_provenance(self):
        @dataclass
        class DummyPolicy:
            can_export_text: bool

        builder = self._builder()
        states = [_state_record(1000, "frame1"), _state_record(2000, "frame2")]
        batch = {"session_id": "run", "states": states}
        out = builder.process(batch)
        spans = out["spans"]
        edges = out["edges"]
        self.assertTrue(spans)
        spans[0].setdefault("provenance", {})["policy"] = DummyPolicy(True)
        if spans[0].get("evidence"):
            spans[0]["evidence"][0]["policy"] = DummyPolicy(False)
        if edges:
            edges[0].setdefault("provenance", {})["policy"] = DummyPolicy(False)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state_tape.db"
            store = StateTapeStore(path)
            counts = store.insert_batch(spans, edges)
            self.assertGreaterEqual(counts.spans_inserted, 1)


if __name__ == "__main__":
    unittest.main()
