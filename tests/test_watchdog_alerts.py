import unittest

from autocapture_nx.kernel.alerts import derive_alerts


class WatchdogAlertTests(unittest.TestCase):
    def test_watchdog_alert_rules(self) -> None:
        config = {"alerts": {"enabled": True}}
        events = [
            {"event_type": "processing.watchdog.stalled", "event_id": "1", "ts_utc": "2024-01-01T00:00:00+00:00"},
            {"event_type": "processing.watchdog.error", "event_id": "2", "ts_utc": "2024-01-01T00:00:01+00:00"},
            {"event_type": "processing.watchdog.restore", "event_id": "3", "ts_utc": "2024-01-01T00:00:02+00:00"},
        ]
        alerts = derive_alerts(config, events)
        self.assertEqual(len(alerts), 3)
        self.assertEqual(alerts[0]["severity"], "critical")
        self.assertEqual(alerts[1]["severity"], "warning")
        self.assertEqual(alerts[2]["severity"], "info")


if __name__ == "__main__":
    unittest.main()
