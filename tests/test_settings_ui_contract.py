import unittest
from pathlib import Path


class SettingsUIContractTests(unittest.TestCase):
    def test_settings_ui_has_presets_and_toggle(self) -> None:
        html = Path("autocapture/web/ui/index.html").read_text(encoding="utf-8")
        self.assertIn('id="settingsPresetsCard"', html)
        self.assertIn('class="preset-card"', html)
        self.assertIn('id="settingsShowAll"', html)
        self.assertIn('id="settingsList"', html)

    def test_settings_ui_has_group_reset_hook(self) -> None:
        js = Path("autocapture/web/ui/app.js").read_text(encoding="utf-8")
        self.assertIn("Reset group", js)
        self.assertIn("settingsShowAll", js)
        self.assertIn("applyPreset", js)
        self.assertIn("postConfigPatch", js)
        start = js.find("async function postConfigPatch")
        self.assertNotEqual(start, -1, "postConfigPatch function missing")
        snippet = js[start : start + 600]
        self.assertIn("resp.ok", snippet)
        self.assertIn("data.error", snippet)


if __name__ == "__main__":
    unittest.main()
