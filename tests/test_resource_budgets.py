import json
import unittest
from pathlib import Path


class ResourceBudgetTests(unittest.TestCase):
    def test_budget_defaults_present(self) -> None:
        config = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
        runtime_cfg = config.get("runtime", {})
        budgets = runtime_cfg.get("budgets", {})
        self.assertGreater(int(budgets.get("window_budget_ms", 0) or 0), 0)
        self.assertLessEqual(int(budgets.get("preempt_grace_ms", 0) or 0), 1000)
        gpu_cfg = runtime_cfg.get("gpu", {})
        self.assertIn("release_vram_on_active", gpu_cfg)
        self.assertIn("release_vram_deadline_ms", gpu_cfg)
        job_limits = runtime_cfg.get("job_limits", {}).get("capture", {})
        self.assertGreater(int(job_limits.get("max_memory_mb", 0) or 0), 0)
        hosting_limits = config.get("plugins", {}).get("hosting", {}).get("job_limits", {})
        self.assertGreater(int(hosting_limits.get("max_memory_mb", 0) or 0), 0)


if __name__ == "__main__":
    unittest.main()
