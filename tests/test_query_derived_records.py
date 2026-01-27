import io
import unittest
import zipfile

from autocapture_nx.kernel.query import extract_on_demand
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.retrieval_basic.plugin import RetrievalStrategy


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


class QueryDerivedRecordTests(unittest.TestCase):
    def test_extract_on_demand_creates_derived_record(self) -> None:
        metadata = _MetadataStore()
        record_id = "run1/segment/0"
        metadata.put(record_id, {"record_type": "evidence.capture.segment", "ts_utc": "2024-01-01T00:00:00+00:00"})

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("frame_0.jpg", b"frame")
        media = _MediaStore({record_id: buf.getvalue()})

        system = {
            "storage.media": media,
            "storage.metadata": metadata,
            "ocr.engine": _Extractor("ocr text"),
            "vision.extractor": _Extractor("vlm text"),
        }

        processed = extract_on_demand(system, time_window=None, limit=2)
        self.assertEqual(processed, 2)
        self.assertNotIn("text", metadata.get(record_id))
        encoded = encode_record_id_component(record_id)
        vlm_provider = encode_record_id_component("vision.extractor")
        ocr_provider = encode_record_id_component("ocr.engine")
        vlm_id = f"run1/derived.text.vlm/{vlm_provider}/{encoded}"
        ocr_id = f"run1/derived.text.ocr/{ocr_provider}/{encoded}"
        derived_vlm = metadata.get(vlm_id)
        derived_ocr = metadata.get(ocr_id)
        self.assertEqual(derived_vlm["record_type"], "derived.text.vlm")
        self.assertEqual(derived_ocr["record_type"], "derived.text.ocr")
        self.assertEqual(derived_vlm["source_id"], record_id)
        self.assertEqual(derived_ocr["source_id"], record_id)
        self.assertEqual(derived_vlm["text"], "vlm text")
        self.assertEqual(derived_ocr["text"], "ocr text")

    def test_retrieval_returns_source_id_for_derived_records(self) -> None:
        metadata = _MetadataStore()
        record_id = "run1/segment/1"
        metadata.put(record_id, {"record_type": "evidence.capture.segment", "ts_utc": "2024-01-02T00:00:00+00:00"})
        encoded = encode_record_id_component(record_id)
        vlm_provider = encode_record_id_component("vision.extractor")
        metadata.put(
            f"run1/derived.text.vlm/{vlm_provider}/{encoded}",
            {
                "record_type": "derived.text.vlm",
                "ts_utc": "2024-01-02T00:00:00+00:00",
                "text": "hello world",
                "source_id": record_id,
                "provider_id": "vision.extractor",
            },
        )
        ctx = PluginContext(config={}, get_capability=lambda _k: metadata, logger=lambda _m: None)
        retrieval = RetrievalStrategy("retrieval", ctx)

        results = retrieval.search("hello", time_window=None)
        self.assertTrue(results)
        self.assertEqual(results[0]["record_id"], record_id)
        self.assertEqual(results[0]["derived_id"], f"run1/derived.text.vlm/{vlm_provider}/{encoded}")


if __name__ == "__main__":
    unittest.main()
