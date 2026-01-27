import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from autocapture.indexing.lexical import LexicalIndex
from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps
from autocapture_nx.processing.sst.pipeline import SSTPipeline

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - optional dependency guard
    Image = None
    ImageDraw = None


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


class _EventBuilder:
    def __init__(self) -> None:
        self.journal: list[tuple[str, str]] = []
        self.ledger: list[tuple[str, str]] = []

    def journal_event(self, event_type: str, payload: dict[str, Any], **_kwargs: Any) -> str:
        # Enforce canonical-json compatibility (no floats).
        canonical_dumps(payload)
        self.journal.append((event_type, payload["artifact_id"]))
        return payload["artifact_id"]

    def ledger_entry(self, stage: str, **kwargs: Any) -> str:
        payload = kwargs.get("payload", {})
        canonical_dumps(payload)
        self.ledger.append((stage, payload.get("artifact_id", "entry")))
        return payload.get("artifact_id", "entry")


class _OCRProvider:
    def __init__(self, text: str, bbox: tuple[int, int, int, int], confidence: int) -> None:
        self._text = text
        self._bbox = bbox
        self._confidence = confidence

    def extract_tokens(self, _image_bytes: bytes) -> list[dict[str, Any]]:
        return [
            {
                "text": self._text,
                "bbox": self._bbox,
                "confidence": self._confidence / 10000.0,
            }
        ]


class _MultiOCR:
    def __init__(self, providers: dict[str, Any]) -> None:
        self._providers = providers

    def items(self) -> list[tuple[str, Any]]:
        return list(self._providers.items())


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


def _make_image_bytes() -> bytes:
    assert Image is not None and ImageDraw is not None
    img = Image.new("RGB", (320, 180), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((16, 16), "Alpha 123", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _contains_bytes(obj: Any) -> bool:
    if isinstance(obj, (bytes, bytearray)):
        return True
    if isinstance(obj, dict):
        return any(_contains_bytes(v) for v in obj.values())
    if isinstance(obj, (list, tuple, set)):
        return any(_contains_bytes(v) for v in obj)
    return False


@unittest.skipIf(Image is None, "Pillow is required for SST pipeline tests")
class SSTPipelineTests(unittest.TestCase):
    def test_pipeline_persists_derived_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _load_default_config()
            storage = config.setdefault("storage", {})
            storage["lexical_path"] = str(Path(tmpdir) / "lexical.db")
            storage["vector_path"] = str(Path(tmpdir) / "vector.db")
            storage["data_dir"] = str(tmpdir)
            sst = config.setdefault("processing", {}).setdefault("sst", {})
            sst["heavy_always"] = True
            sst["redact_enabled"] = False

            metadata = _MetadataStore()
            events = _EventBuilder()
            ocr = _MultiOCR(
                {
                    "ocr.high": _OCRProvider("Alpha", (0, 0, 320, 40), 9000),
                    "ocr.low": _OCRProvider("Alpha", (0, 0, 320, 40), 4000),
                }
            )
            system = _System(
                config,
                {
                    "storage.metadata": metadata,
                    "ocr.engine": ocr,
                    "event.builder": events,
                },
            )

            pipeline = SSTPipeline(system, extractor_id="test.sst", extractor_version="0.1.0")
            record_id = "run1/segment/0"
            record = {
                "record_type": "evidence.capture.segment",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "container": {"type": "zip"},
            }
            result = pipeline.process_record(
                record_id=record_id,
                record=record,
                frame_bytes=_make_image_bytes(),
                allow_ocr=True,
                allow_vlm=False,
                should_abort=None,
                deadline_ts=time.time() + 30,
            )

            self.assertTrue(result.heavy_ran)
            self.assertGreater(result.derived_records, 0)
            self.assertGreater(len(result.derived_ids), 0)

            self.assertTrue(any(k.startswith("run1/derived.sst.frame/") for k in metadata.keys()))
            self.assertTrue(any(k.startswith("run1/derived.sst.state/") for k in metadata.keys()))
            self.assertTrue(any(k.startswith("run1/derived.sst.text/state/") for k in metadata.keys()))

            state_key = next(k for k in metadata.keys() if k.startswith("run1/derived.sst.state/"))
            state_payload = metadata.get(state_key, {})
            self.assertIn("screen_state", state_payload)
            self.assertGreater(len(state_payload["screen_state"].get("tokens", ())), 0)

            for record_payload in metadata.data.values():
                self.assertFalse(_contains_bytes(record_payload))

            lexical = LexicalIndex(storage["lexical_path"])
            hits = lexical.query("Alpha", limit=10)
            self.assertTrue(any(hit["doc_id"] in result.derived_ids for hit in hits))


if __name__ == "__main__":
    unittest.main()
