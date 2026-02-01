import unittest

from autocapture.runtime.gpu_guard import evaluate_gpu_lag_guard
from autocapture.runtime.conductor import RuntimeConductor
from autocapture.runtime.governor import RuntimeGovernor
from autocapture_nx.kernel.telemetry import record_telemetry


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
        self._governor.update_config(config)

    def has(self, name: str) -> bool:
        return name in ("tracking.input", "runtime.governor")

    def get(self, name: str):
        if name == "tracking.input":
            return self._tracker
        if name == "runtime.governor":
            return self._governor
        raise KeyError(name)


class GpuLagGuardTests(unittest.TestCase):
    def test_guard_blocks_on_lag(self) -> None:
        config = {
            "runtime": {
                "gpu": {
                    "lag_guard": {
                        "enabled": True,
                        "max_capture_lag_ms": 20,
                        "max_queue_depth_p95": 12,
                        "max_capture_age_s": 2.0,
                    }
                }
            }
        }
        telemetry = {
            "latest": {
                "capture": {"lag_p95_ms": 50, "queue_depth_p95": 1, "last_capture_age_s": 0.1}
            }
        }
        decision = evaluate_gpu_lag_guard(config, telemetry=telemetry)
        self.assertFalse(decision.ok)
        self.assertEqual(decision.reason, "capture_lag")

    def test_gpu_only_allowed_when_guard_ok(self) -> None:
        record_telemetry(
            "capture",
            {"lag_p95_ms": 5, "queue_depth_p95": 1, "last_capture_age_s": 0.2},
        )
        config = {
            "runtime": {
                "idle_window_s": 5,
                "active_window_s": 2,
                "mode_enforcement": {"suspend_workers": True, "suspend_deadline_ms": 500, "idle_resume_budget_ms": 3000},
                "budgets": {
                    "window_s": 60,
                    "window_budget_ms": 1000,
                    "per_job_max_ms": 500,
                    "max_jobs_per_window": 2,
                    "max_heavy_concurrency": 1,
                    "preempt_grace_ms": 0,
                    "min_idle_seconds": 1,
                    "allow_heavy_during_active": False,
                    "cpu_max_utilization": 0.5,
                    "ram_max_utilization": 0.5,
                },
                "telemetry": {"enabled": False, "emit_interval_s": 5},
                "gpu": {
                    "allow_during_active": True,
                    "device_index": 0,
                    "lag_guard": {
                        "enabled": True,
                        "max_capture_lag_ms": 50,
                        "max_queue_depth_p95": 12,
                        "max_capture_age_s": 2.0,
                    },
                    "release_vram_deadline_ms": 250,
                    "release_vram_on_active": True,
                },
            }
        }
        tracker = _Tracker(idle_seconds=0)
        system = _System(config, tracker)
        conductor = RuntimeConductor(system)
        signals = conductor._signals()
        self.assertTrue(signals.get("gpu_only_allowed"))


if __name__ == "__main__":
    unittest.main()
