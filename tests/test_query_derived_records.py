import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from autocapture.core.hashing import hash_text, normalize_text
from autocapture.indexing.lexical import LexicalIndex
from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.query import extract_on_demand
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.retrieval_basic.plugin import RetrievalStrategy
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


class QueryDerivedRecordTests(unittest.TestCase):
    def test_extract_on_demand_creates_derived_record(self) -> None:
        metadata = _MetadataStore()
        record_id = "run1/segment/0"
        evidence = {
            "schema_version": 1,
            "record_type": "evidence.capture.segment",
            "run_id": "run1",
            "segment_id": "seg0",
            "ts_start_utc": "2024-01-01T00:00:00+00:00",
            "ts_end_utc": "2024-01-01T00:00:10+00:00",
            "ts_utc": "2024-01-01T00:00:00+00:00",
            "width": 1,
            "height": 1,
            "container": {"type": "zip"},
            "content_hash": "hash",
        }
        evidence["payload_hash"] = sha256_canonical({k: v for k, v in evidence.items() if k != "payload_hash"})
        metadata.put(record_id, evidence)

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
        vlm_id = derived_text_record_id(
            kind="vlm",
            run_id="run1",
            provider_id="vision.extractor",
            source_id=record_id,
            config={},
        )
        ocr_id = derived_text_record_id(
            kind="ocr",
            run_id="run1",
            provider_id="ocr.engine",
            source_id=record_id,
            config={},
        )
        derived_vlm = metadata.get(vlm_id)
        derived_ocr = metadata.get(ocr_id)
        self.assertEqual(derived_vlm["record_type"], "derived.text.vlm")
        self.assertEqual(derived_ocr["record_type"], "derived.text.ocr")
        self.assertEqual(derived_vlm["source_id"], record_id)
        self.assertEqual(derived_ocr["source_id"], record_id)
        self.assertEqual(derived_vlm["text"], "vlm text")
        self.assertEqual(derived_ocr["text"], "ocr text")
        self.assertEqual(derived_vlm["content_hash"], hash_text(normalize_text("vlm text")))
        self.assertEqual(derived_ocr["content_hash"], hash_text(normalize_text("ocr text")))

    def test_retrieval_returns_source_id_for_derived_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _MetadataStore()
            record_id = "run1/segment/1"
            evidence = {
                "schema_version": 1,
                "record_type": "evidence.capture.segment",
                "run_id": "run1",
                "segment_id": "seg1",
                "ts_start_utc": "2024-01-02T00:00:00+00:00",
                "ts_end_utc": "2024-01-02T00:00:10+00:00",
                "ts_utc": "2024-01-02T00:00:00+00:00",
                "width": 1,
                "height": 1,
                "container": {"type": "zip"},
                "content_hash": "hash",
            }
            evidence["payload_hash"] = sha256_canonical({k: v for k, v in evidence.items() if k != "payload_hash"})
            metadata.put(record_id, evidence)
            derived_id = derived_text_record_id(
                kind="vlm",
                run_id="run1",
                provider_id="vision.extractor",
                source_id=record_id,
                config={},
            )
            derived = {
                "schema_version": 1,
                "record_type": "derived.text.vlm",
                "run_id": "run1",
                "ts_utc": "2024-01-02T00:00:00+00:00",
                "text": "hello world",
                "source_id": record_id,
                "parent_evidence_id": record_id,
                "span_ref": {"kind": "time", "source_id": record_id},
                "method": "vlm",
                "provider_id": "vision.extractor",
                "model_id": "vision.extractor",
                "model_digest": "digest",
                "content_hash": hash_text(normalize_text("hello world")),
            }
            derived["payload_hash"] = sha256_canonical({k: v for k, v in derived.items() if k != "payload_hash"})
            metadata.put(derived_id, derived)
            lexical_path = Path(tmp) / "lexical.db"
            vector_path = Path(tmp) / "vector.db"
            lexical = LexicalIndex(lexical_path)
            lexical.index(derived_id, "hello world")
            config = {
                "storage": {"lexical_path": str(lexical_path), "vector_path": str(vector_path)},
                "indexing": {"vector_backend": "sqlite"},
                "retrieval": {"vector_enabled": False},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: metadata, logger=lambda _m: None)
            retrieval = RetrievalStrategy("retrieval", ctx)

            results = retrieval.search("hello", time_window=None)
            self.assertTrue(results)
            self.assertEqual(results[0]["record_id"], record_id)
            self.assertEqual(results[0]["derived_id"], derived_id)


if __name__ == "__main__":
    unittest.main()
