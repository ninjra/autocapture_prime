import tempfile
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.builder_jepa import JEPAStateBuilder
from autocapture_nx.state_layer.jepa_training import JEPATraining


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


class JEPAInferenceTests(unittest.TestCase):
    def _config(self, data_dir: str, *, training_enabled: bool) -> dict:
        return {
            "storage": {"data_dir": data_dir},
            "processing": {
                "state_layer": {
                    "features": {"training_enabled": training_enabled},
                    "builder": {
                        "text_weight": 1.0,
                        "vision_weight": 0.6,
                        "layout_weight": 0.4,
                        "input_weight": 0.2,
                    },
                    "training": {
                        "latent_dim": 16,
                        "learning_rate": 0.01,
                        "epochs": 2,
                        "max_samples": 50,
                        "init_scale": 0.02,
                        "weight_scale": 1000000,
                        "error_clip": 1.0,
                        "projection_seed": "",
                        "seed": "test-seed",
                        "auto_approve": False,
                    },
                }
            },
        }

    def test_builder_uses_approved_model(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            states = [
                _state_record(1000, "frame1", "Hello World"),
                _state_record(7000, "frame2", "Hello Again"),
            ]
            base_ctx = PluginContext(
                config=self._config(tmp_dir, training_enabled=False),
                get_capability=lambda _name: None,
                logger=lambda *_args, **_kwargs: None,
                rng=None,
                rng_seed=None,
                rng_seed_hex=None,
            )
            base_builder = JEPAStateBuilder("test.builder", base_ctx)
            base_out = base_builder.process({"session_id": "run", "states": states})
            base_span = base_out["spans"][0]

            trainer = JEPATraining("test.training", base_ctx)
            train_result = trainer.train({"spans": base_out["spans"], "edges": base_out["edges"]})
            trainer.approve_model(train_result["model_version"], train_result["training_run_id"])

            model_ctx = PluginContext(
                config=self._config(tmp_dir, training_enabled=True),
                get_capability=lambda _name: None,
                logger=lambda *_args, **_kwargs: None,
                rng=None,
                rng_seed=None,
                rng_seed_hex=None,
            )
            model_builder = JEPAStateBuilder("test.builder", model_ctx)
            model_out = model_builder.process({"session_id": "run", "states": states})
            model_span = model_out["spans"][0]
            self.assertEqual(model_span["provenance"]["model_version"], train_result["model_version"])
            self.assertNotEqual(base_span["z_embedding"]["blob"], model_span["z_embedding"]["blob"])


if __name__ == "__main__":
    unittest.main()
