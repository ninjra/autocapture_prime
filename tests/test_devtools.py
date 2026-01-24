import json
import os
import unittest
from pathlib import Path

from autocapture_nx.kernel.loader import Kernel, default_config_paths


class DevtoolsTests(unittest.TestCase):
    def test_diffusion_harness_creates_artifacts(self):
        kernel = Kernel(default_config_paths(), safe_mode=False)
        system = kernel.boot()
        harness = system.get("devtools.diffusion")
        result = harness.run(axis="test", k_variants=1, dry_run=True)
        run_dir = Path(result["run_dir"])
        self.assertTrue((run_dir / "run.json").exists())
        scorecard = run_dir / "scorecard_v1.json"
        self.assertTrue(scorecard.exists())

    def test_ast_ir_pinned(self):
        kernel = Kernel(default_config_paths(), safe_mode=False)
        system = kernel.boot()
        tool = system.get("devtools.ast_ir")
        result = tool.run(scan_root="autocapture_nx")
        self.assertTrue(result["pinned_ok"])


if __name__ == "__main__":
    unittest.main()
