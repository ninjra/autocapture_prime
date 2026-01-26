import unittest
import shutil

from autocapture_nx.capture.pipeline import _resolve_container


class CaptureContainerResolutionTests(unittest.TestCase):
    def test_ffmpeg_container_requires_binary(self) -> None:
        resolved, path = _resolve_container("ffmpeg_mp4", "")
        ffmpeg_present = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
        if ffmpeg_present:
            self.assertEqual(resolved, "ffmpeg_mp4")
            self.assertTrue(path)
        else:
            self.assertEqual(resolved, "avi_mjpeg")
            self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
