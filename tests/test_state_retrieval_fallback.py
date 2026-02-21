import tempfile
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.builder_jepa import JEPAStateBuilder
from autocapture_nx.state_layer.jepa_training import JEPATraining
from autocapture_nx.state_layer.retrieval import StateRetrieval
from autocapture_nx.state_layer.store_sqlite import StateTapeStore


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


class RetrievalFallbackTests(unittest.TestCase):
    def _config(self, data_dir: str, training_enabled: bool) -> dict:
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
                        "activation": "tanh",
                        "projection_seed": "",
                        "seed": "fallback",
                        "auto_approve": False,
                        "fallback_enabled": True,
                        "retention": {
                            "enabled": False,
                            "max_active_models": 3,
                            "archive_unapproved": False,
                            "archive_dir": "",
                        },
                    },
                    "index": {"top_k": 5, "min_score": 0.0, "max_candidates": 200},
                }
            },
        }

    def test_retrieval_fallback_uses_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            states = [
                _state_record(1000, "frame1", "Alpha Notes"),
                _state_record(7000, "frame2", "Beta Notes"),
            ]
            base_ctx = PluginContext(
                config=self._config(tmp_dir, training_enabled=False),
                get_capability=lambda _name: None,
                logger=lambda *_args, **_kwargs: None,
                rng=None,
                rng_seed=None,
                rng_seed_hex=None,
            )
            builder = JEPAStateBuilder("test.builder", base_ctx)
            out = builder.process({"session_id": "run", "states": states})
            store = StateTapeStore(f"{tmp_dir}/state.db")
            store.insert_batch(out["spans"], out["edges"])

            trainer = JEPATraining("test.training", base_ctx)
            train_result = trainer.train({"spans": out["spans"], "edges": out["edges"]})
            trainer.approve_model(train_result["model_version"], train_result["training_run_id"])

            ctx = PluginContext(
                config=self._config(tmp_dir, training_enabled=True),
                get_capability=lambda name: store if name == "storage.state_tape" else None,
                logger=lambda *_args, **_kwargs: None,
                rng=None,
                rng_seed=None,
                rng_seed_hex=None,
            )
            retrieval = StateRetrieval("test.retrieval", ctx)
            hits = retrieval.search("Alpha", limit=3)
            self.assertTrue(hits)


if __name__ == "__main__":
    unittest.main()
