import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.builder_jepa import JEPAStateBuilder


def _state_record(ts_ms: int, frame_id: str, text: str) -> dict:
    tokens = [
        {
            "token_id": f"t{idx}",
            "text": word,
            "norm_text": word.lower(),
            "bbox": (10 * idx, 10, 10 * idx + 5, 20),
            "confidence_bp": 9000,
        }
        for idx, word in enumerate(text.split(), start=1)
    ]
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
            "tokens": tokens,
            "visible_apps": ["app"],
            "element_graph": {"elements": [], "edges": []},
            "text_blocks": [],
            "tables": [],
            "spreadsheets": [],
            "code_blocks": [],
            "charts": [],
        },
    }


def _state_record_missing_frame_id(ts_ms: int, record_id: str, text: str) -> dict:
    record = _state_record(ts_ms, "missing", text)
    record["record_id"] = record_id
    record["source_id"] = record_id
    screen_state = record.get("screen_state", {})
    if isinstance(screen_state, dict):
        screen_state["frame_id"] = ""
        record["screen_state"] = screen_state
    return record


class StateLayerBuilderTests(unittest.TestCase):
    def _builder(self):
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

    def test_builder_is_deterministic(self):
        builder = self._builder()
        states = [
            _state_record(1000, "frame1", "Hello World"),
            _state_record(2000, "frame2", "Hello Again"),
        ]
        batch = {"session_id": "run", "states": states}
        out1 = builder.process(batch)
        out2 = builder.process(batch)
        self.assertEqual(out1["spans"], out2["spans"])
        self.assertEqual(out1["edges"], out2["edges"])
        self.assertTrue(out1["spans"])

    def test_builder_falls_back_to_record_id_for_evidence(self):
        builder = self._builder()
        states = [
            _state_record_missing_frame_id(1000, "frameA", "Hello World"),
            _state_record_missing_frame_id(2000, "frameB", "Hello Again"),
        ]
        batch = {"session_id": "run", "states": states}
        out = builder.process(batch)
        self.assertTrue(out["spans"])
        evidence = out["spans"][0].get("evidence", [])
        self.assertTrue(evidence)
        self.assertEqual(evidence[0].get("media_id"), "frameA")


if __name__ == "__main__":
    unittest.main()
