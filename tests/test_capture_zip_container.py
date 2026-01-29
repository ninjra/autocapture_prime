import tempfile
import unittest
import zipfile

from autocapture_nx.capture.pipeline import SegmentWriter
from autocapture_nx.windows.win_capture import Frame


class CaptureZipContainerTests(unittest.TestCase):
    def test_zip_container_uses_store_compression(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            segment = SegmentWriter(
                tmpdir,
                "run1/segment/0",
                fps_target=30,
                bitrate_kbps=8000,
                container_type="zip",
                encoder="cpu",
                ffmpeg_path=None,
                frame_format="jpeg",
            )
            frame = Frame(ts_utc="t0", data=b"jpeg", width=1, height=1, ts_monotonic=0.0)
            segment.add_frame(frame)
            segment.add_frame(frame)
            artifact = segment.finalize()
            self.assertIsNotNone(artifact)
            self.assertTrue(artifact.path.endswith(".zip"))
            with zipfile.ZipFile(artifact.path, "r") as zf:
                infos = zf.infolist()
                self.assertTrue(infos)
                self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in infos))


if __name__ == "__main__":
    unittest.main()
