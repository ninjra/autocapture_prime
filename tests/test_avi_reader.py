import tempfile
import unittest

from autocapture_nx.capture.avi import AviMjpegReader, AviMjpegWriter


class AviReaderTests(unittest.TestCase):
    def test_avi_writer_and_reader_roundtrip(self) -> None:
        jpeg_bytes = b"\xff\xd8\xff\xd9"
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/segment.avi"
            writer = AviMjpegWriter(path, width=1, height=1, fps=1)
            writer.add_frame(jpeg_bytes)
            writer.add_frame(jpeg_bytes)
            writer.close(duration_ms=2000)

            with open(path, "rb") as handle:
                data = handle.read()
            reader = AviMjpegReader(data)
            first = reader.first_frame()
            reader.close()
            self.assertEqual(first, jpeg_bytes)


if __name__ == "__main__":
    unittest.main()
