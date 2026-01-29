import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autocapture_nx.kernel.paths import apply_path_defaults


class PreferredWindowsPathTests(unittest.TestCase):
    def test_preferred_windows_data_dir_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"paths": {"preferred_data_dir_windows": tmpdir}}
            with patch("autocapture_nx.kernel.paths.os.name", "nt"):
                updated = apply_path_defaults(config, user_overrides={})
            data_dir = Path(updated.get("storage", {}).get("data_dir", ""))
            self.assertEqual(data_dir.resolve(), Path(tmpdir).resolve())
            paths = updated.get("paths", {})
            self.assertEqual(Path(paths.get("data_dir", "")).resolve(), Path(tmpdir).resolve())


if __name__ == "__main__":
    unittest.main()
