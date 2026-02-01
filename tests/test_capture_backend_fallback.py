import os
import unittest

from autocapture_nx.capture.pipeline import _resolve_backend


@unittest.skipUnless(os.name == "nt", "Windows-only capture backend fallback test")
class CaptureBackendFallbackTests(unittest.TestCase):
    def test_dd_nvenc_fallback(self) -> None:
        backend, reason = _resolve_backend(
            "dd_nvenc",
            {"dd_nvenc": {"allow_fallback": True}},
            ffmpeg_path=None,
            monitor_index=0,
        )
        self.assertEqual(backend, "mss_jpeg")
        self.assertEqual(reason, "nvenc_unavailable")

    def test_dd_nvenc_no_fallback(self) -> None:
        with self.assertRaises(RuntimeError):
            _resolve_backend(
                "dd_nvenc",
                {"dd_nvenc": {"allow_fallback": False}},
                ffmpeg_path=None,
                monitor_index=0,
            )


if __name__ == "__main__":
    unittest.main()
