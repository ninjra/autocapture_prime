import json
import unittest
from pathlib import Path

from autocapture.ux.plugin_options import build_plugin_options


class PluginOptionsTests(unittest.TestCase):
    def test_capture_options_exposed(self) -> None:
        config = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
        options = build_plugin_options(config)
        self.assertIn("builtin.capture.windows", options)
        paths = [item["path"] for item in options["builtin.capture.windows"]]
        self.assertIn("capture.video.backend", paths)


if __name__ == "__main__":
    unittest.main()
