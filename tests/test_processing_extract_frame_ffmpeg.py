import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.processing.idle import _extract_frame


class ProcessingExtractFrameFfmpegTests(unittest.TestCase):
    def test_extract_frame_from_ffmpeg_mp4_segment(self) -> None:
        ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
        if not ffmpeg:
            self.skipTest("ffmpeg not available")

        screenshot = resolve_repo_path("docs/test sample/Screenshot 2026-02-02 113519.png")
        if not screenshot.exists():
            self.skipTest("fixture screenshot missing")

        # Create a tiny MP4 from the screenshot. Use mpeg4 for broad availability.
        with tempfile.TemporaryDirectory(prefix="acp_ffmpeg_") as td:
            out = Path(td) / "segment.mp4"
            env = os.environ.copy()
            env.setdefault("OMP_NUM_THREADS", "1")
            env.setdefault("OPENBLAS_NUM_THREADS", "1")
            env.setdefault("MKL_NUM_THREADS", "1")
            env.setdefault("NUMEXPR_NUM_THREADS", "1")
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-loop",
                "1",
                "-i",
                str(screenshot),
                "-t",
                "0.2",
                "-r",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "mpeg4",
                "-q:v",
                "2",
                str(out),
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=20.0)
            if proc.returncode != 0:
                self.skipTest("ffmpeg encoder unavailable for test")
            blob = out.read_bytes()

        record = {"record_type": "evidence.capture.segment", "container": {"type": "ffmpeg_mp4"}}
        frame = _extract_frame(blob, record, config={"capture": {"video": {"ffmpeg_path": ffmpeg}}})
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertTrue(frame.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()

