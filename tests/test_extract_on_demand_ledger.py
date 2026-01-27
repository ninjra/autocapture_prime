import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from autocapture_nx.kernel.query import extract_on_demand


class _MetaStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def put(self, record_id: str, value: dict) -> None:
        self._data[record_id] = value

    def put_new(self, record_id: str, value: dict) -> None:
        if record_id in self._data:
            raise FileExistsError(record_id)
        self._data[record_id] = value

    def get(self, record_id: str, default=None):
        return self._data.get(record_id, default)

    def keys(self):
        return list(self._data.keys())


class _MediaStore:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def get(self, record_id: str, default=None):
        return self._blobs.get(record_id, default)


class _Extractor:
    def extract(self, _frame_bytes: bytes) -> dict:
        return {"text": "hello world"}


class _EventBuilder:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def journal_event(self, _event_type: str, _payload: dict, **_kwargs) -> None:
        return None

    def ledger_entry(self, stage: str, inputs: list[str], outputs: list[str], *, payload=None, **_kwargs) -> str:
        self.entries.append({"stage": stage, "inputs": inputs, "outputs": outputs, "payload": payload})
        return "hash"


class _System:
    def __init__(self, metadata, media, builder, config) -> None:
        self._caps = {
            "storage.metadata": metadata,
            "storage.media": media,
            "ocr.engine": _Extractor(),
            "event.builder": builder,
        }
        self.config = config

    def get(self, name: str):
        return self._caps[name]

    def has(self, name: str) -> bool:
        return name in self._caps


class ExtractOnDemandLedgerTests(unittest.TestCase):
    def test_extract_records_ledger_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _MetaStore()
            evidence_id = "run1/segment/0"
            meta.put(
                evidence_id,
                {
                    "record_type": "evidence.capture.segment",
                    "run_id": "run1",
                    "ts_utc": "2026-01-01T00:00:00+00:00",
                    "container": {"type": "zip"},
                },
            )
            frame_zip = io.BytesIO()
            with zipfile.ZipFile(frame_zip, "w") as zf:
                zf.writestr("frame.bin", b"frame")
            media = _MediaStore({evidence_id: frame_zip.getvalue()})
            builder = _EventBuilder()
            config = {
                "runtime": {"run_id": "run1"},
                "processing": {"sst": {"enabled": False}},
                "storage": {
                    "lexical_path": str(Path(tmp) / "lexical.db"),
                    "vector_path": str(Path(tmp) / "vector.db"),
                },
            }
            system = _System(meta, media, builder, config)
            processed = extract_on_demand(
                system,
                None,
                limit=1,
                allow_ocr=True,
                allow_vlm=False,
                collected_ids=[],
                candidate_ids=[evidence_id],
            )
            self.assertEqual(processed, 1)
            stages = [entry["stage"] for entry in builder.entries]
            self.assertIn("derived.extract", stages)


if __name__ == "__main__":
    unittest.main()
