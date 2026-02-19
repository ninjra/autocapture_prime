import tempfile
import unittest
from pathlib import Path

from autocapture.capture.spool import CaptureSpool
from autocapture.capture.models import CaptureSegment


class CaptureSpoolIdempotentTests(unittest.TestCase):
    def test_idempotent_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = CaptureSpool(Path(tmp))
            segment = CaptureSegment(segment_id="seg1", ts_utc="2026-01-01T00:00:00Z", blob_id="blob", metadata={})
            first = spool.append(segment)
            second = spool.append(segment)
            self.assertTrue(first)
            self.assertTrue(second)
            self.assertEqual(spool.list_segments(), ["seg1"])

    def test_collision_raises_when_payload_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = CaptureSpool(Path(tmp))
            first = CaptureSegment(segment_id="seg1", ts_utc="2026-01-01T00:00:00Z", blob_id="blob", metadata={})
            second = CaptureSegment(segment_id="seg1", ts_utc="2026-01-01T00:00:00Z", blob_id="blob2", metadata={})
            self.assertTrue(spool.append(first))
            with self.assertRaisesRegex(RuntimeError, "spool_collision"):
                spool.append(second)


if __name__ == "__main__":
    unittest.main()
