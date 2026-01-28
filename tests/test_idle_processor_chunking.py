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
    def journal_event(self, *_args, **_kwargs):
        return "event"

    def ledger_entry(self, *_args, **_kwargs):
        return "hash"


class _System:
    def __init__(self, config, metadata, media, ocr, events):
        self.config = config
        self._caps = {
            "storage.metadata": metadata,
            "storage.media": media,
            "ocr.engine": ocr,
            "event.builder": events,
        }

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str):
        return self._caps[name]


class IdleProcessorChunkingTests(unittest.TestCase):
    def test_chunked_processing_persists_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory():
            config = {
                "runtime": {"run_id": "run1"},
                "processing": {
                    "idle": {
                        "enabled": True,
                        "max_items_per_run": 1,
                        "max_seconds_per_run": 10,
                        "extractors": {"ocr": True, "vlm": False},
                    }
                },
            }
            metadata = _MetadataStore()
            media_blobs = {}
            for idx in range(2):
                record_id = f"run1/segment/{idx}"
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
                media_blobs[record_id] = buf.getvalue()

            media = _MediaStore(media_blobs)
            events = _EventBuilder()
            system = _System(config, metadata, media, _Extractor("ocr text"), events)
            processor = IdleProcessor(system)

            done, stats = processor.process_step(budget_ms=0)
            self.assertFalse(done)
            self.assertEqual(stats.processed, 1)
            checkpoint_id = "run1/derived.idle.checkpoint"
            self.assertIn(checkpoint_id, metadata.data)

            done, stats = processor.process_step(budget_ms=0)
            self.assertTrue(done)
            self.assertEqual(stats.processed, 1)


if __name__ == "__main__":
    unittest.main()
