import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.builder_jepa import JEPAStateBuilder
from autocapture_nx.state_layer.processor import StateTapeProcessor
from autocapture_nx.state_layer.store_sqlite import StateTapeStore


class _MetadataStore:
    def __init__(self) -> None:
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def put(self, key, value):
        self.data[key] = value

    def put_replace(self, key, value):
        self.data[key] = value

    def keys(self):
        return list(self.data.keys())


class _System:
    def __init__(self, config, caps):
        self.config = config
        self._caps = caps

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str):
        return self._caps[name]


def _state_record(ts_ms: int, frame_id: str) -> dict:
    return {
        "record_type": "derived.sst.state",
        "run_id": "run",
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


class StateTapeProcessorTests(unittest.TestCase):
    def test_processor_writes_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state_tape.db"
            store = StateTapeStore(state_path)
            metadata = _MetadataStore()
            record_id = "run/derived.sst.state/rid_frame1"
            metadata.data[record_id] = _state_record(1000, "frame1")

            config = {
                "processing": {
                    "state_layer": {
                        "enabled": True,
                        "emit_frame_evidence": True,
                        "builder": {
                            "text_weight": 1.0,
                            "vision_weight": 0.6,
                            "layout_weight": 0.4,
                            "input_weight": 0.2,
                        },
                        "windowing_mode": "fixed_duration",
                        "window_ms": 5000,
                        "max_evidence_refs": 3,
                        "batch": {"max_states_per_run": 10, "overlap_states": 1},
                        "features": {"index_enabled": False, "workflow_enabled": False, "anomaly_enabled": False, "training_enabled": False},
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
            builder = JEPAStateBuilder("test.state.builder", ctx)
            system = _System(
                config,
                {
                    "storage.metadata": metadata,
                    "storage.state_tape": store,
                    "state.builder": builder,
                },
            )
            processor = StateTapeProcessor(system)
            done, stats = processor.process_step()
            self.assertTrue(done)
            self.assertGreaterEqual(stats.spans_inserted, 1)
            self.assertTrue(store.get_spans())


if __name__ == "__main__":
    unittest.main()
