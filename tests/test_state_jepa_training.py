import base64
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.jepa_training import JEPATraining


class JEPATrainingTests(unittest.TestCase):
    def _trainer(self, tmp_dir: str):
        config = {
            "storage": {"data_dir": tmp_dir},
            "processing": {"state_layer": {"builder": {}}},
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

    def _span(self, state_id: str, ts_ms: int, vec):
        data = b"".join(struct.pack("e", float(v)) for v in vec)
        return {
            "state_id": state_id,
            "ts_start_ms": ts_ms,
            "z_embedding": {"dim": len(vec), "dtype": "f16", "blob": base64.b64encode(data).decode("ascii")},
        }

    def test_training_outputs_and_approval_gate(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            trainer = self._trainer(tmp_dir)
            dataset = {
                "spans": [self._span("s1", 0, [1, 0, 0, 0]), self._span("s2", 1, [0, 1, 0, 0])],
                "edges": [{"edge_id": "e1"}],
                "evidence": [{"sha256": "aa"}],
            }
            result = trainer.train(dataset)
            self.assertIn("model_version", result)
            self.assertIn("training_run_id", result)
            model_version = result["model_version"]
            training_run_id = result["training_run_id"]
            model_dir = Path(result["artifact_dir"])
            self.assertTrue((model_dir / "model.json").exists())
            self.assertTrue((model_dir / "model.sig").exists())
            self.assertTrue((model_dir / "report.json").exists())

            report = trainer.report(model_version, training_run_id)
            self.assertTrue(report.get("ok"))
            self.assertEqual(report.get("report", {}).get("model_version"), model_version)

            with self.assertRaises(PermissionError):
                trainer.load_model(model_version, training_run_id)

            trainer.approve_model(model_version, training_run_id)
            payload = trainer.load_model(model_version, training_run_id)
            self.assertEqual(payload.get("model_version"), model_version)

            model_path = model_dir / "model.json"
            model_path.write_text(json.dumps({"tampered": True}), encoding="utf-8")
            with self.assertRaises(PermissionError):
                trainer.load_model(model_version, training_run_id)

    def test_model_version_mismatch_blocks_load(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            trainer = self._trainer(tmp_dir)
            result = trainer.train({"spans": [self._span("s1", 0, [1, 0, 0, 0]), self._span("s2", 1, [0, 1, 0, 0])]})
            trainer.approve_model(result["model_version"], result["training_run_id"])
            with self.assertRaises(ValueError):
                trainer.load_model(
                    result["model_version"],
                    result["training_run_id"],
                    expected_model_version="other",
                )

    def test_approve_latest_and_promote(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            trainer = self._trainer(tmp_dir)
            result_a = trainer.train({"spans": [self._span("s1", 0, [1, 0, 0, 0]), self._span("s2", 1, [0, 1, 0, 0])]})
            result_b = trainer.train({"spans": [self._span("s3", 2, [0, 0, 1, 0]), self._span("s4", 3, [0, 0, 0, 1])]})
            approved = trainer.approve_latest()
            self.assertTrue(approved.get("approved"))
            trainer.approve_model(result_a["model_version"], result_a["training_run_id"])
            trainer.approve_model(result_b["model_version"], result_b["training_run_id"])
            trainer.promote_model(result_a["model_version"], result_a["training_run_id"])
            latest = trainer.latest_approved()
            self.assertIsNotNone(latest)
            self.assertEqual(latest.get("model_version"), result_a["model_version"])

    def test_data_dir_falls_back_to_env_when_storage_scoped_out(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old = os.environ.get("AUTOCAPTURE_DATA_DIR")
            try:
                os.environ["AUTOCAPTURE_DATA_DIR"] = tmp_dir
                ctx = PluginContext(
                    config={"processing": {"state_layer": {"builder": {}}}},
                    get_capability=lambda _name: None,
                    logger=lambda *_args, **_kwargs: None,
                    rng=None,
                    rng_seed=None,
                    rng_seed_hex=None,
                )
                trainer = JEPATraining("test.training", ctx)
                self.assertTrue(str(trainer._root).startswith(str(Path(tmp_dir))))
            finally:
                if old is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = old


if __name__ == "__main__":
    unittest.main()
