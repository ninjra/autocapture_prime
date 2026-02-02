import base64
import struct
import tempfile
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.jepa_training import JEPATraining


def _span(state_id: str, ts_ms: int, vec):
    data = b"".join(struct.pack("e", float(v)) for v in vec)
    return {
        "state_id": state_id,
        "ts_start_ms": ts_ms,
        "z_embedding": {"dim": len(vec), "dtype": "f16", "blob": base64.b64encode(data).decode("ascii")},
    }


class JEPARetentionTests(unittest.TestCase):
    def _trainer(self, tmp_dir: str):
        config = {
            "storage": {"data_dir": tmp_dir},
            "processing": {
                "state_layer": {
                    "builder": {},
                    "training": {
                        "latent_dim": 8,
                        "learning_rate": 0.01,
                        "epochs": 2,
                        "max_samples": 50,
                        "init_scale": 0.02,
                        "weight_scale": 1000000,
                        "error_clip": 1.0,
                        "activation": "tanh",
                        "projection_seed": "",
                        "seed": "retention",
                        "auto_approve": False,
                        "fallback_enabled": True,
                        "retention": {
                            "enabled": True,
                            "max_active_models": 1,
                            "archive_unapproved": False,
                            "archive_dir": "",
                        },
                    },
                }
            },
        }
        ctx = PluginContext(
            config=config,
            get_capability=lambda _name: None,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        return JEPATraining("test.training", ctx)

    def test_retention_archives_oldest_approved(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            trainer = self._trainer(tmp_dir)
            result_a = trainer.train({"spans": [_span("s1", 0, [1, 0, 0, 0]), _span("s2", 1, [0, 1, 0, 0])]})
            trainer.approve_model(result_a["model_version"], result_a["training_run_id"])

            result_b = trainer.train({"spans": [_span("s1", 0, [1, 0, 0, 0]), _span("s2", 1, [0, 0, 1, 0])]})
            trainer.approve_model(result_b["model_version"], result_b["training_run_id"])

            models = trainer.list_models(include_archived=True)
            archived = [m for m in models if m.get("archived_ts_ms")]
            self.assertTrue(archived)
            latest = trainer.latest_approved()
            self.assertIsNotNone(latest)
            self.assertEqual(latest["model_version"], result_b["model_version"])


if __name__ == "__main__":
    unittest.main()
