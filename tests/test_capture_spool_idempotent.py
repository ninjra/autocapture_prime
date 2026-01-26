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
            self.assertFalse(second)
            self.assertEqual(spool.list_segments(), ["seg1"])


if __name__ == "__main__":
    unittest.main()
