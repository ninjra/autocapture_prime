import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from autocapture.storage.pressure import DiskPressureSample
from autocapture_nx.kernel.telemetry import record_telemetry
from autocapture_nx.ux.facade import UXFacade


class CaptureStatusPayloadTests(unittest.TestCase):
    def test_capture_status_uses_latest_telemetry(self) -> None:
        now = datetime.now(timezone.utc)
        record_telemetry(
            "capture.output",
            {
                "ts_utc": now.isoformat(),
                "record_id": "run1/segment/0",
                "record_type": "evidence.capture.segment",
                "output_bytes": 1,
                "frame_count": 1,
                "write_ms": 1,
                "backend": "mss",
            },
        )
        sample = DiskPressureSample(
            ts_utc=now.isoformat(),
            free_bytes=10,
            total_bytes=20,
            used_bytes=10,
            free_gb=1,
            hard_halt=False,
            evidence_bytes=0,
            derived_bytes=0,
            metadata_bytes=0,
            lexical_bytes=0,
            vector_bytes=0,
            level="ok",
        )
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            facade = UXFacade(persistent=False)
            try:
                with patch("autocapture.storage.pressure.sample_disk_pressure", return_value=sample):
                    status = facade._capture_status_payload()
                self.assertEqual(status.get("last_capture_ts_utc"), now.isoformat())
                age = status.get("last_capture_age_seconds")
                self.assertIsNotNone(age)
                self.assertLessEqual(float(age), 5.0)
                self.assertIn("disk", status)
            finally:
                facade.shutdown()
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data


if __name__ == "__main__":
    unittest.main()
