import unittest

from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.scheduler import Scheduler, Job


class GovernorGatingTests(unittest.TestCase):
    def test_governor_modes(self) -> None:
        governor = RuntimeGovernor(idle_window_s=10)
        self.assertEqual(governor.decide({"user_active": True, "idle_seconds": 1, "query_intent": False}).mode, "ACTIVE_CAPTURE_ONLY")
        self.assertEqual(governor.decide({"user_active": False, "idle_seconds": 15, "query_intent": False}).mode, "IDLE_DRAIN")
        self.assertEqual(governor.decide({"user_active": False, "idle_seconds": 1, "query_intent": True}).mode, "USER_QUERY")

    def test_scheduler_respects_modes(self) -> None:
        governor = RuntimeGovernor(idle_window_s=5)
        scheduler = Scheduler(governor)
        ran = []
        scheduler.enqueue(Job(name="heavy", fn=lambda: ran.append("heavy"), heavy=True))
        scheduler.enqueue(Job(name="light", fn=lambda: ran.append("light"), heavy=False))

        scheduler.run_pending({"user_active": True, "idle_seconds": 1, "query_intent": False})
        self.assertEqual(ran, [])

        scheduler.run_pending({"user_active": False, "idle_seconds": 10, "query_intent": False})
        self.assertEqual(ran, ["heavy", "light"])


if __name__ == "__main__":
    unittest.main()
