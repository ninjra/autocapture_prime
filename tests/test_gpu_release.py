import unittest
from unittest.mock import patch

from autocapture.runtime.conductor import RuntimeConductor
from autocapture.runtime.governor import RuntimeGovernor


class _Tracker:
    def __init__(self, idle_seconds: float) -> None:
        self._idle = idle_seconds

    def idle_seconds(self) -> float:
        return self._idle


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


class GpuReleaseTests(unittest.TestCase):
    def test_release_vram_on_active(self) -> None:
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
                },
                "gpu": {"release_vram_on_active": True, "release_vram_deadline_ms": 1},
                "telemetry": {"enabled": False, "emit_interval_s": 5},
            },
            "processing": {"idle": {"enabled": False}},
            "research": {"enabled": False},
        }
        tracker = _Tracker(idle_seconds=0)
        system = _System(config, tracker)
        conductor = RuntimeConductor(system)
        with patch("autocapture.runtime.conductor.release_vram") as release:
            conductor._run_once()
            self.assertTrue(release.called)

    def test_release_vram_disabled(self) -> None:
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
                },
                "gpu": {"release_vram_on_active": False, "release_vram_deadline_ms": 1},
                "telemetry": {"enabled": False, "emit_interval_s": 5},
            },
            "processing": {"idle": {"enabled": False}},
            "research": {"enabled": False},
        }
        tracker = _Tracker(idle_seconds=0)
        system = _System(config, tracker)
        conductor = RuntimeConductor(system)
        with patch("autocapture.runtime.conductor.release_vram") as release:
            conductor._run_once()
            self.assertFalse(release.called)


if __name__ == "__main__":
    unittest.main()
