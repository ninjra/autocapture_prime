import io
import unittest
import zipfile

from autocapture_nx.processing.idle import IdleProcessor


class _MetadataStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

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


def _zip_blob() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("frame_0.jpg", b"frame")
    return buf.getvalue()


class PrivacyExcludedGatingTests(unittest.TestCase):
    def test_privacy_excluded_skips_derived(self) -> None:
        config = {
            "runtime": {"run_id": "run1"},
            "processing": {
                "idle": {
                    "enabled": True,
                    "max_items_per_run": 1,
                    "max_seconds_per_run": 5,
                    "extractors": {"ocr": True, "vlm": False},
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
                "privacy_excluded": True,
            },
        )
        media = _MediaStore({record_id: _zip_blob()})
        events = _EventBuilder()
        system = _System(config, metadata, media, _Extractor("ocr text"), events)
        processor = IdleProcessor(system)

        _done, stats = processor.process_step(budget_ms=0)

        self.assertEqual(stats.processed, 0)
        self.assertGreaterEqual(stats.skipped, 1)
        self.assertIn(record_id, metadata.data)
        derived = [
            k
            for k in metadata.data.keys()
            if k.startswith("run1/derived.") and k != "run1/derived.idle.checkpoint"
        ]
        self.assertEqual(derived, [])


if __name__ == "__main__":
    unittest.main()
