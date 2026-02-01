import unittest

from autocapture_nx import tray


class TrayMenuPolicyTests(unittest.TestCase):
    def test_tray_menu_has_no_capture_pause_or_delete(self) -> None:
        menu = tray._default_menu(lambda: None, lambda: None, lambda: None)
        labels = [str(item[1]).lower() for item in menu]
        self.assertTrue(all("pause" not in label for label in labels))
        self.assertTrue(all("delete" not in label for label in labels))


if __name__ == "__main__":
    unittest.main()
