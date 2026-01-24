import os
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.capture_windows.plugin import CaptureWindows
from plugins.builtin.audio_windows.plugin import AudioCaptureWindows
from plugins.builtin.input_windows.plugin import InputTrackerWindows
from plugins.builtin.window_metadata_windows.plugin import WindowMetadataWindows


@unittest.skipUnless(os.name == "nt", "Windows-only tests")
class WindowsPluginTests(unittest.TestCase):
    def test_capture_requires_windows(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        cap = CaptureWindows("cap", ctx)
        self.assertTrue(hasattr(cap, "start"))

    def test_audio_requires_windows(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        audio = AudioCaptureWindows("aud", ctx)
        self.assertTrue(hasattr(audio, "start"))

    def test_input_requires_windows(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        inp = InputTrackerWindows("inp", ctx)
        self.assertTrue(hasattr(inp, "start"))

    def test_window_metadata_requires_windows(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        wm = WindowMetadataWindows("wm", ctx)
        self.assertTrue(hasattr(wm, "start"))


if __name__ == "__main__":
    unittest.main()
