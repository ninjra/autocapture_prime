import os
import unittest
from pathlib import Path
import tempfile

from autocapture_nx.kernel.loader import Kernel, default_config_paths


class DevtoolsTests(unittest.TestCase):
    def test_diffusion_harness_creates_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                kernel = Kernel(default_config_paths(), safe_mode=False)
                system = kernel.boot()
                try:
                    harness = system.get("devtools.diffusion")
                    result = harness.run(axis="test", k_variants=1, dry_run=True)
                    run_dir = Path(result["run_dir"])
                    self.assertTrue((run_dir / "run.json").exists())
                    scorecard = run_dir / "scorecard_v1.json"
                    self.assertTrue(scorecard.exists())
                finally:
                    kernel.shutdown()
            finally:
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data

    def test_ast_ir_pinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                kernel = Kernel(default_config_paths(), safe_mode=False)
                system = kernel.boot()
                try:
                    tool = system.get("devtools.ast_ir")
                    result = tool.run(scan_root="autocapture_nx")
                    self.assertTrue(result["pinned_ok"])
                finally:
                    kernel.shutdown()
            finally:
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data


if __name__ == "__main__":
    unittest.main()
