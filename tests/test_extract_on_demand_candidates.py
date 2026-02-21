import io
import unittest
import zipfile

from autocapture_nx.kernel.query import extract_on_demand
from autocapture_nx.kernel.derived_records import derived_text_record_id


class _MediaStore:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def get(self, record_id: str):
        return self._blobs.get(record_id)


class _MetadataStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def put(self, record_id: str, value: dict) -> None:
        self.data[record_id] = value

    def get(self, record_id: str, default=None):
        return self.data.get(record_id, default)

    def keys(self):
        return list(self.data.keys())


class _Extractor:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract(self, _frame: bytes):
        return {"text": self._text}


class ExtractOnDemandCandidateTests(unittest.TestCase):
    def test_candidate_filter_limits_extraction(self) -> None:
        metadata = _MetadataStore()
        record_a = "run1/segment/0"
        record_b = "run1/segment/1"
        for record_id in (record_a, record_b):
            metadata.put(record_id, {"record_type": "evidence.capture.segment", "ts_utc": "2024-01-01T00:00:00+00:00"})

        def _zip_blob() -> bytes:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("frame_0.jpg", b"frame")
            return buf.getvalue()

        media = _MediaStore({record_a: _zip_blob(), record_b: _zip_blob()})

        system = {
            "storage.media": media,
            "storage.metadata": metadata,
            "ocr.engine": _Extractor("ocr text"),
        }

        processed = extract_on_demand(system, time_window=None, limit=5, allow_ocr=True, allow_vlm=False, candidate_ids=[record_a])
        self.assertEqual(processed, 1)
        ocr_a = derived_text_record_id(kind="ocr", run_id="run1", provider_id="ocr.engine", source_id=record_a, config={})
        ocr_b = derived_text_record_id(kind="ocr", run_id="run1", provider_id="ocr.engine", source_id=record_b, config={})
        self.assertIn(ocr_a, metadata.data)
        self.assertNotIn(ocr_b, metadata.data)


if __name__ == "__main__":
    unittest.main()
