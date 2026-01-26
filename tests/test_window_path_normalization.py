import unittest

from autocapture_nx.windows.win_window import normalize_device_path


class WindowPathNormalizationTests(unittest.TestCase):
    def test_device_path_normalized(self) -> None:
        mappings = [
            (r"\\Device\\HarddiskVolume2", "C:"),
            (r"\\Device\\HarddiskVolume1", "D:"),
        ]
        path = r"\\Device\\HarddiskVolume2\\Windows\\System32\\notepad.exe"
        normalized = normalize_device_path(path, mappings)
        self.assertEqual(normalized, r"C:\\Windows\\System32\\notepad.exe")

    def test_unmapped_path_passthrough(self) -> None:
        mappings = [(r"\\Device\\HarddiskVolume3", "E:")]
        path = r"\\Device\\HarddiskVolume2\\Windows\\System32\\notepad.exe"
        normalized = normalize_device_path(path, mappings)
        self.assertEqual(normalized, path)


if __name__ == "__main__":
    unittest.main()
