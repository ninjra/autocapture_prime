import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from autocapture.indexing.lexical import LexicalIndex
from autocapture_nx.kernel.derived_records import derived_text_record_id
from autocapture_nx.processing.idle import IdleProcessor
from autocapture_nx.plugin_system.registry import CapabilityProxy, MultiCapabilityProxy


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


class _System:
    def __init__(self, config: dict, caps: dict[str, object]) -> None:
        self.config = config
        self._caps = caps

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str):
        return self._caps[name]


class IdleMultiExtractorTests(unittest.TestCase):
    def test_idle_processor_fanout_indexes_each_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lexical_path = root / "lexical.db"
            vector_path = root / "vector.db"
            config = {
                "storage": {
                    "data_dir": str(root),
                    "lexical_path": str(lexical_path),
                    "vector_path": str(vector_path),
                },
                "indexing": {"vector_backend": "sqlite", "embedder_model": None},
                "processing": {
                    "idle": {
                        "enabled": True,
                        "max_items_per_run": 10,
                        "max_seconds_per_run": 30,
                        "extractors": {"ocr": True, "vlm": False},
                    }
                },
                "plugins": {"capabilities": {}},
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

            policy = {
                "mode": "multi",
                "preferred": [],
                "provider_ids": [],
                "fanout": True,
                "max_providers": 4,
            }
            ocr_multi = MultiCapabilityProxy(
                "ocr.engine",
                [
                    ("ocr.one", CapabilityProxy(_Extractor("text one"), False)),
                    ("ocr.two", CapabilityProxy(_Extractor("text two"), False)),
                ],
                policy,
            )
            caps = {
                "storage.metadata": metadata,
                "storage.media": media,
                "ocr.engine": CapabilityProxy(ocr_multi, False),
            }
            system = _System(config, caps)

            processor = IdleProcessor(system)
            stats = processor.process()
            self.assertEqual(stats.processed, 2)

            for provider in ("ocr.one", "ocr.two"):
                derived_id = derived_text_record_id(
                    kind="ocr",
                    run_id="run1",
                    provider_id=provider,
                    source_id=record_id,
                    config=config,
                )
                self.assertIn(derived_id, metadata.data)
                self.assertEqual(metadata.data[derived_id]["provider_id"], provider)

            lexical = LexicalIndex(lexical_path)
            self.assertGreaterEqual(lexical.count(), 2)


if __name__ == "__main__":
    unittest.main()
