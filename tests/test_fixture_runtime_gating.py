import unittest

from autocapture_nx.ux.fixture import run_idle_processing


class _Tracker:
    def idle_seconds(self) -> float:
        return 0.0


class _System:
    def __init__(self) -> None:
        self.config = {
            "runtime": {
                "active_window_s": 3,
                "activity": {"assume_idle_when_missing": False},
                "mode_enforcement": {"suspend_workers": True},
                "budgets": {"cpu_max_utilization": 0.5, "ram_max_utilization": 0.5},
            }
        }
        self._caps = {"tracking.input": _Tracker()}

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str):
        return self._caps.get(name)


class FixtureRuntimeGatingTests(unittest.TestCase):
    def test_active_user_blocks_idle(self) -> None:
        system = _System()
        result = run_idle_processing(system, max_steps=1, timeout_s=1.0)
        self.assertFalse(bool(result.get("done")))
        blocked = result.get("blocked") or {}
        self.assertEqual(blocked.get("reason"), "active_user")


if __name__ == "__main__":
    unittest.main()
