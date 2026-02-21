import unittest

from autocapture.runtime.conductor import RuntimeConductor
from autocapture.runtime.governor import RuntimeGovernor
from autocapture_nx.windows.fullscreen import fullscreen_snapshot


class _Tracker:
    def __init__(self, idle_seconds: float) -> None:
        self._idle = idle_seconds

    def idle_seconds(self) -> float:
        return self._idle


class _WindowTracker:
    def __init__(self, record: dict) -> None:
        self._record = record

    def last_record(self) -> dict:
        return self._record


class _IdleProcessor:
    def __init__(self) -> None:
        self.called = 0

    def process(self, **_kwargs):
        self.called += 1


class _System:
    def __init__(self, config: dict, tracker: _Tracker, window_tracker: _WindowTracker) -> None:
        self.config = config
        self._tracker = tracker
        self._window_tracker = window_tracker
        self._governor = RuntimeGovernor(idle_window_s=int(config["runtime"]["idle_window_s"]))
        self._governor.update_config(config)

    def has(self, name: str) -> bool:
        return name in ("tracking.input", "window.metadata", "runtime.governor")

    def get(self, name: str):
        if name == "tracking.input":
            return self._tracker
        if name == "window.metadata":
            return self._window_tracker
        if name == "runtime.governor":
            return self._governor
        raise KeyError(name)


class FullscreenHaltTests(unittest.TestCase):
    def test_fullscreen_snapshot_from_window_record(self) -> None:
        record = {
            "window": {
                "rect": [0, 0, 100, 100],
                "monitor": {"rect": [0, 0, 100, 100]},
            }
        }
        snap = fullscreen_snapshot(record)
        self.assertTrue(snap.fullscreen)

        record = {
            "window": {
                "rect": [10, 10, 90, 90],
                "monitor": {"rect": [0, 0, 100, 100]},
            }
        }
        snap = fullscreen_snapshot(record)
        self.assertFalse(snap.fullscreen)

    def test_conductor_halts_processing_when_fullscreen(self) -> None:
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
                "fullscreen_halt": {"enabled": True, "poll_ms": 1},
                "telemetry": {"enabled": False, "emit_interval_s": 5},
                "gpu": {
                    "allow_during_active": False,
                    "device_index": 0,
                    "lag_guard": {
                        "enabled": False,
                        "max_capture_lag_ms": 50,
                        "max_queue_depth_p95": 12,
                        "max_capture_age_s": 2.0,
                    },
                    "release_vram_deadline_ms": 250,
                    "release_vram_on_active": True,
                },
            },
            "processing": {"idle": {"enabled": True, "sleep_ms": 1}},
            "research": {"enabled": False, "run_on_idle": False, "interval_s": 0},
        }
        tracker = _Tracker(idle_seconds=20)
        window_record = {
            "window": {"rect": [0, 0, 100, 100], "monitor": {"rect": [0, 0, 100, 100]}}
        }
        system = _System(config, tracker, _WindowTracker(window_record))
        conductor = RuntimeConductor(system)
        idle = _IdleProcessor()
        conductor._idle_processor = idle

        executed = conductor._run_once()
        self.assertNotIn("idle.extract", executed)


if __name__ == "__main__":
    unittest.main()
