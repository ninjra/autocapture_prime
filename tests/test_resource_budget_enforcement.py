import unittest

from autocapture.runtime.governor import RuntimeGovernor


class ResourceBudgetEnforcementTests(unittest.TestCase):
    def test_cpu_budget_blocks_idle_work(self) -> None:
        governor = RuntimeGovernor(idle_window_s=5)
        governor.update_config(
            {
                "runtime": {
                    "budgets": {
                        "cpu_max_utilization": 0.5,
                        "ram_max_utilization": 0.5,
                    }
                }
            }
        )
        decision = governor.decide(
            {"user_active": False, "idle_seconds": 10, "cpu_utilization": 0.6}
        )
        self.assertEqual(decision.mode, "ACTIVE_CAPTURE_ONLY")
        self.assertEqual(decision.reason, "resource_budget")

    def test_ram_budget_blocks_idle_work(self) -> None:
        governor = RuntimeGovernor(idle_window_s=5)
        governor.update_config(
            {
                "runtime": {
                    "budgets": {
                        "cpu_max_utilization": 0.5,
                        "ram_max_utilization": 0.5,
                    }
                }
            }
        )
        decision = governor.decide(
            {"user_active": False, "idle_seconds": 10, "ram_utilization": 0.7}
        )
        self.assertEqual(decision.mode, "ACTIVE_CAPTURE_ONLY")
        self.assertEqual(decision.reason, "resource_budget")


if __name__ == "__main__":
    unittest.main()
