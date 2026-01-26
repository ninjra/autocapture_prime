import io
import tempfile
import unittest
import zipfile

from autocapture_nx.processing.idle import IdleProcessor


class _MetadataStore:
    def __init__(self) -> None:
        self.data = {}

    def put_new(self, record_id: str, value: dict) -> None:
        if record_id in self.data:
            raise FileExistsError(record_id)
        self.data[record_id] = value

    def put(self, record_id: str, value: dict) -> None:
        self.data[record_id] = value

    def get(self, record_id: str, default=None):
        return self.data.get(record_id, default)

    def keys(self):
        return list(self.data.keys())


class _MediaStore:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def get(self, record_id: str):
        return self._blobs.get(record_id)


class _Extractor:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract(self, _frame: bytes):
        return {"text": self._text}


class _EventBuilder:
    def __init__(self) -> None:
        self.journal = []
        self.ledger = []

    def journal_event(self, event_type, payload, **kwargs):
        self.journal.append((event_type, payload))
        return payload.get("derived_id") or "event"

    def ledger_entry(self, stage, inputs, outputs, **kwargs):
        self.ledger.append((stage, inputs, outputs))
        return "hash"


class _System:
    def __init__(self, config, metadata, media, ocr, vlm, events):
        self.config = config
        self._caps = {
            "storage.metadata": metadata,
            "storage.media": media,
            "ocr.engine": ocr,
            "vision.extractor": vlm,
            "event.builder": events,
        }

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str):
        return self._caps[name]


class IdleProcessorTests(unittest.TestCase):
    def test_idle_processor_writes_derived_records(self) -> None:
        with tempfile.TemporaryDirectory():
            config = {
                "runtime": {"run_id": "run1"},
                "processing": {
                    "idle": {
                        "enabled": True,
                        "auto_start": False,
                        "max_items_per_run": 10,
                        "max_seconds_per_run": 5,
                        "sleep_ms": 1,
                        "max_concurrency_cpu": 1,
                        "max_concurrency_gpu": 1,
                        "extractors": {"ocr": True, "vlm": True},
                    }
                },
            }
            metadata = _MetadataStore()
            record_id = "run1/segment/0"
            metadata.put(
                record_id,
                {
                    "record_type": "evidence.capture.segment",
                    "ts_utc": "2024-01-01T00:00:00+00:00",
                    "container": {"type": "zip"},
                },
            )
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("frame_0.jpg", b"frame")
            media = _MediaStore({record_id: buf.getvalue()})
            events = _EventBuilder()
            system = _System(config, metadata, media, _Extractor("ocr text"), _Extractor("vlm text"), events)

            processor = IdleProcessor(system)
            stats = processor.process()
            self.assertEqual(stats.processed, 2)
            self.assertIn("run1/derived.text.ocr/run1_segment_0", metadata.data)
            self.assertIn("run1/derived.text.vlm/run1_segment_0", metadata.data)


if __name__ == "__main__":
    unittest.main()
