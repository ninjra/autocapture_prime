import unittest

from autocapture_nx.kernel.alerts import derive_alerts


class SilenceAlertTests(unittest.TestCase):
    def test_capture_silence_alert(self) -> None:
        config = {"alerts": {"enabled": True}}
        events = [
            {"event_type": "capture.silence", "event_id": "1", "ts_utc": "2024-01-01T00:00:00+00:00"}
        ]
        alerts = derive_alerts(config, events)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "critical")
        self.assertEqual(alerts[0]["title"], "Capture silent while active")


if __name__ == "__main__":
    unittest.main()
