import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps
from autocapture_nx.processing.idle import IdleProcessor
from autocapture_nx.processing.sst.pipeline import SSTPipeline

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency guard
    Image = None


class _MetadataStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    def put_new(self, record_id: str, value: dict[str, Any]) -> None:
        if record_id in self.data:
            raise FileExistsError(record_id)
        self.data[record_id] = value

    def put(self, record_id: str, value: dict[str, Any]) -> None:
        self.data[record_id] = value

    def get(self, record_id: str, default: Any | None = None) -> Any:
        return self.data.get(record_id, default)

    def keys(self) -> list[str]:
        return list(self.data.keys())


class _MediaStore:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def get(self, record_id: str) -> bytes | None:
        return self._blobs.get(record_id)


class _EventBuilder:
    def journal_event(self, _event_type: str, payload: dict[str, Any], **_kwargs: Any) -> str:
        canonical_dumps(payload)
        return payload.get("artifact_id", "event")

    def ledger_entry(self, _stage: str, **kwargs: Any) -> str:
        payload = kwargs.get("payload", {})
        canonical_dumps(payload)
        return payload.get("artifact_id", "entry")


class _OCRProvider:
    def extract_tokens(self, _image_bytes: bytes) -> list[dict[str, Any]]:
        return [{"text": "Idle Alpha", "bbox": (0, 0, 320, 40), "confidence": 0.95}]


class _System:
    def __init__(self, config: dict[str, Any], caps: dict[str, Any]) -> None:
        self.config = config
        self._caps = caps

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str) -> Any:
        return self._caps[name]


def _load_default_config() -> dict[str, Any]:
    path = Path("config/default.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_blob() -> bytes:
    assert Image is not None
    img = Image.new("RGB", (320, 180), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("frame_0.png", data)
    return zbuf.getvalue()


@unittest.skipIf(Image is None, "Pillow is required for SST idle tests")
class IdleSSTPipelineTests(unittest.TestCase):
    def test_idle_processor_uses_sst_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _load_default_config()
            storage = config.setdefault("storage", {})
            storage["lexical_path"] = str(Path(tmpdir) / "lexical.db")
            storage["vector_path"] = str(Path(tmpdir) / "vector.db")
            storage["data_dir"] = str(tmpdir)

            processing = config.setdefault("processing", {})
            processing.setdefault("idle", {}).update(
                {
                    "enabled": True,
                    "auto_start": False,
                    "max_items_per_run": 5,
                    "max_seconds_per_run": 10,
                    "sleep_ms": 1,
                    "max_concurrency_cpu": 1,
                    "max_concurrency_gpu": 1,
                    "extractors": {"ocr": True, "vlm": False},
                }
            )
            sst = processing.setdefault("sst", {})
            sst["heavy_always"] = True

            metadata = _MetadataStore()
            record_id = "run1/segment/1"
            metadata.put(
                record_id,
                {
                    "record_type": "evidence.capture.segment",
                    "ts_utc": "2024-01-01T00:00:00+00:00",
                    "container": {"type": "zip"},
                },
            )
            media = _MediaStore({record_id: _frame_blob()})
            events = _EventBuilder()
            system = _System(
                config,
                {
                    "storage.metadata": metadata,
                    "storage.media": media,
                    "ocr.engine": _OCRProvider(),
                    "event.builder": events,
                },
            )
            pipeline = SSTPipeline(system, extractor_id="test.sst", extractor_version="0.1.0")
            system._caps["processing.pipeline"] = pipeline

            processor = IdleProcessor(system)
            stats = processor.process(should_abort=lambda: time.time() < 0)

            self.assertEqual(stats.sst_runs, 1)
            self.assertEqual(stats.sst_heavy, 1)
            self.assertGreater(stats.processed, 0)
            self.assertTrue(any(k.startswith("run1/derived.sst.state/") for k in metadata.keys()))


if __name__ == "__main__":
    unittest.main()

