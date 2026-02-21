import unittest

from autocapture_nx.capture.screenshot_policy import schedule_from_config


class ScreenshotPolicyTests(unittest.TestCase):
    def test_activity_enabled_active(self) -> None:
        cfg = {
            "activity": {
                "enabled": True,
                "active_window_s": 3.0,
                "active_interval_s": 0.5,
                "idle_interval_s": 60.0,
                "assume_active_when_missing": True,
            },
            "fps_target": 2,
            "dedupe": {"force_interval_s": 60},
        }
        sched = schedule_from_config(cfg, idle_seconds=0.1)
        self.assertEqual(sched.mode, "active")
        self.assertAlmostEqual(sched.interval_s, 0.5)
        self.assertAlmostEqual(sched.force_interval_s, 0.0)

    def test_activity_enabled_idle(self) -> None:
        cfg = {
            "activity": {
                "enabled": True,
                "active_window_s": 3.0,
                "active_interval_s": 0.5,
                "idle_interval_s": 60.0,
                "assume_active_when_missing": True,
            },
            "fps_target": 2,
            "dedupe": {"force_interval_s": 60},
        }
        sched = schedule_from_config(cfg, idle_seconds=10.0)
        self.assertEqual(sched.mode, "idle")
        self.assertAlmostEqual(sched.interval_s, 60.0)
        self.assertAlmostEqual(sched.force_interval_s, 60.0)

    def test_activity_enabled_missing_idle_seconds_assumes_active(self) -> None:
        cfg = {
            "activity": {"enabled": True, "active_interval_s": 0.5, "idle_interval_s": 60.0, "assume_active_when_missing": True},
            "fps_target": 2,
            "dedupe": {"force_interval_s": 60},
        }
        sched = schedule_from_config(cfg, idle_seconds=None)
        self.assertEqual(sched.mode, "active")
        self.assertAlmostEqual(sched.interval_s, 0.5)
        self.assertAlmostEqual(sched.force_interval_s, 0.0)


if __name__ == "__main__":
    unittest.main()

