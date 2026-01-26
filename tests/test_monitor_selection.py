import unittest

from autocapture_nx.windows.win_window import MonitorInfo, select_monitor_for_rect


class MonitorSelectionTests(unittest.TestCase):
    def test_selects_monitor_containing_center(self) -> None:
        monitors = [
            MonitorInfo(device="MON1", rect=(0, 0, 1920, 1080)),
            MonitorInfo(device="MON2", rect=(1920, 0, 3840, 1080)),
        ]
        rect = (2000, 100, 2100, 200)
        chosen = select_monitor_for_rect(rect, monitors)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.device, "MON2")

    def test_falls_back_to_first_monitor(self) -> None:
        monitors = [MonitorInfo(device="MON1", rect=(0, 0, 100, 100))]
        rect = (200, 200, 300, 300)
        chosen = select_monitor_for_rect(rect, monitors)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.device, "MON1")


if __name__ == "__main__":
    unittest.main()
