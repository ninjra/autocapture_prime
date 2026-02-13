from __future__ import annotations

from autocapture_nx.runtime.governor import RuntimeGovernor


def test_governor_blocks_heavy_when_resource_limits_exceeded() -> None:
    gov = RuntimeGovernor()
    gov.update_config(
        {
            "runtime": {
                "budgets": {
                    "cpu_max_utilization": 0.5,
                    "ram_max_utilization": 0.5,
                    "window_budget_ms": 1000,
                    "max_jobs_per_window": 10,
                },
                "activity": {"assume_idle_when_missing": False},
            }
        }
    )
    decision = gov.decide(
        {
            "idle_seconds": 999,
            "user_active": False,
            "cpu_utilization": 0.95,
            "ram_utilization": 0.1,
        }
    )
    assert decision.mode == "ACTIVE_CAPTURE_ONLY"
    assert decision.reason == "resource_budget"
    assert decision.heavy_allowed is False

