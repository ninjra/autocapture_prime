from __future__ import annotations

import unittest

from autocapture_nx.windows.win_paths import normalize_windows_path_str, windows_is_within


class WindowsPathNormalizationTests(unittest.TestCase):
    def test_normalize_strips_win32_namespace_prefix(self) -> None:
        self.assertEqual(
            normalize_windows_path_str(r"\\?\C:\Data\..\Data\file.txt"),
            normalize_windows_path_str(r"c:\data\file.txt"),
        )

    def test_is_within_denies_parent_traversal(self) -> None:
        root = r"C:\data"
        self.assertTrue(windows_is_within(root, r"C:\data\ok.txt"))
        self.assertFalse(windows_is_within(root, r"C:\data\..\secret.txt"))

    def test_is_within_handles_unc(self) -> None:
        root = r"\\server\share\data"
        self.assertTrue(windows_is_within(root, r"\\server\share\data\sub\file.txt"))
        self.assertFalse(windows_is_within(root, r"\\server\share\other\file.txt"))


if __name__ == "__main__":
    unittest.main()

