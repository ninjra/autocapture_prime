import unittest

from autocapture.runtime.conductor import RuntimeConductor
from autocapture.runtime.governor import RuntimeGovernor


class _Tracker:
    def __init__(self, idle_seconds: float) -> None:
        self._idle = idle_seconds

    def idle_seconds(self) -> float:
        return self._idle


class _IdleProcessor:
    def __init__(self) -> None:
        self.called = 0

    def process(self, **_kwargs):
        self.called += 1


class _ResearchRunner:
    def __init__(self) -> None:
        self.called = 0

    def run_once(self):
        self.called += 1
        return {"ok": True}


class _PromptOpsOptimizer:
    def __init__(self, *, due: bool = True) -> None:
        self.called = 0
        self._due = due

    def due(self) -> bool:
        return bool(self._due)

    def run_once(self, *, user_active: bool, idle_seconds: float | None = None, force: bool = False):
        self.called += 1
        return {
            "ok": True,
            "user_active": bool(user_active),
            "idle_seconds": float(idle_seconds or 0.0),
            "force": bool(force),
        }


class _System:
    def __init__(self, config: dict, tracker: _Tracker) -> None:
        self.config = config
        self._tracker = tracker
        self._governor = RuntimeGovernor(idle_window_s=int(config["runtime"]["idle_window_s"]))

    def has(self, name: str) -> bool:
        return name in ("tracking.input", "runtime.governor")

    def get(self, name: str):
        if name == "tracking.input":
            return self._tracker
        if name == "runtime.governor":
            return self._governor
        raise KeyError(name)


class RuntimeConductorTests(unittest.TestCase):
    def test_idle_jobs_only_when_idle(self) -> None:
        config = {
            "runtime": {
                "idle_window_s": 10,
                "active_window_s": 2,
                "mode_enforcement": {"suspend_workers": True},
                "budgets": {
                    "window_s": 600,
                    "window_budget_ms": 8000,
                    "per_job_max_ms": 2500,
                    "max_jobs_per_window": 4,
                    "max_heavy_concurrency": 1,
                    "preempt_grace_ms": 0,
                    "min_idle_seconds": 10,
                    "allow_heavy_during_active": False,
                    # Keep this unit test focused on idle gating, not host resource noise.
                    "cpu_max_utilization": 1.0,
                    "ram_max_utilization": 1.0,
                },
                "telemetry": {"enabled": False, "emit_interval_s": 5},
            },
            "processing": {"idle": {"enabled": True, "sleep_ms": 1}},
            "promptops": {
                "optimizer": {
                    "enabled": True,
                    "interval_s": 300,
                    "estimate_ms": 200,
                }
            },
            "research": {"enabled": True, "run_on_idle": True, "interval_s": 0},
        }
        tracker = _Tracker(idle_seconds=20)
        system = _System(config, tracker)
        conductor = RuntimeConductor(system)
        conductor._idle_processor = _IdleProcessor()
        conductor._promptops_optimizer = _PromptOpsOptimizer(due=True)
        conductor._research_runner = _ResearchRunner()

        executed = conductor._run_once()
        self.assertIn("idle.extract", executed)
        self.assertIn("promptops.optimize", executed)
        self.assertEqual(conductor._promptops_optimizer.called, 1)
        self.assertNotIn("idle.research", executed)
        self.assertEqual(conductor._research_runner.called, 0)

        tracker._idle = 0
        executed = conductor._run_once()
        self.assertNotIn("idle.extract", executed)
        self.assertNotIn("promptops.optimize", executed)
        self.assertEqual(conductor._promptops_optimizer.called, 1)

    def test_idle_budget_job_limit(self) -> None:
        config = {
            "runtime": {
                "idle_window_s": 5,
                "active_window_s": 2,
                "mode_enforcement": {"suspend_workers": True},
                "budgets": {
                    "window_s": 600,
                    "window_budget_ms": 8000,
                    "per_job_max_ms": 2500,
                    "max_jobs_per_window": 1,
                    "max_heavy_concurrency": 1,
                    "preempt_grace_ms": 0,
                    "min_idle_seconds": 5,
                    "allow_heavy_during_active": False,
                    # Keep this unit test focused on job-window limits, not host resource noise.
                    "cpu_max_utilization": 1.0,
                    "ram_max_utilization": 1.0,
                },
                "telemetry": {"enabled": False, "emit_interval_s": 5},
            },
            "processing": {"idle": {"enabled": True, "sleep_ms": 1}},
            "research": {"enabled": False, "run_on_idle": False, "interval_s": 0},
        }
        tracker = _Tracker(idle_seconds=30)
        system = _System(config, tracker)
        conductor = RuntimeConductor(system)
        idle = _IdleProcessor()
        conductor._idle_processor = idle

        conductor._run_once()
        self.assertEqual(idle.called, 1)
        conductor._run_once()
        self.assertEqual(idle.called, 1)


if __name__ == "__main__":
    unittest.main()
