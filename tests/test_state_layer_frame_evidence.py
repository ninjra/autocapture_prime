import base64
import unittest

from autocapture_nx.kernel.frame_evidence import ensure_frame_evidence


class _MetadataStore:
    def __init__(self) -> None:
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def put_new(self, key, value):
        if key in self.data:
            raise FileExistsError(key)
        self.data[key] = value

    def put(self, key, value):
        self.data[key] = value


class _MediaStore:
    def __init__(self) -> None:
        self.data = {}

    def put_new(self, key, value, ts_utc=None):
        if key in self.data:
            raise FileExistsError(key)
        self.data[key] = value

    def put(self, key, value, ts_utc=None):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)


class FrameEvidenceTests(unittest.TestCase):
    def test_segment_frame_evidence_created(self) -> None:
        config = {
            "processing": {
                "state_layer": {
                    "enabled": True,
                    "emit_frame_evidence": True,
                    "segment_frame_index": 0,
                }
            }
        }
        metadata = _MetadataStore()
        media = _MediaStore()
        segment_id = "run/segment/1"
        record = {
            "record_type": "evidence.capture.segment",
            "run_id": "run",
            "segment_id": segment_id,
            "ts_start_utc": "2024-01-01T00:00:00+00:00",
            "width": 1,
            "height": 1,
        }
        frame_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
        )
        frame_id, frame_record = ensure_frame_evidence(
            config=config,
            metadata=metadata,
            media=media,
            record_id=segment_id,
            record=record,
            frame_bytes=frame_bytes,
            event_builder=None,
            logger=None,
        )
        self.assertNotEqual(frame_id, segment_id)
        self.assertEqual(frame_record.get("record_type"), "evidence.capture.frame")
        self.assertEqual(frame_record.get("parent_evidence_id"), segment_id)
        self.assertIn(frame_id, metadata.data)
        self.assertIn(frame_id, media.data)


if __name__ == "__main__":
    unittest.main()
