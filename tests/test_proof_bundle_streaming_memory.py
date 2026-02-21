from __future__ import annotations

import io
from pathlib import Path


def test_proof_bundle_uses_streaming_media_reads(tmp_path: Path):
    from autocapture_nx.kernel.proof_bundle import export_proof_bundle

    class Meta:
        def __init__(self):
            self._data = {}

        def get(self, key, default=None):
            return self._data.get(key, default)

        def put_new(self, key, value):
            self._data[key] = value

        def keys(self):
            return list(self._data.keys())

    class Media:
        def __init__(self, blob: bytes):
            self._blob = blob
            self.open_calls = 0

        def open_stream(self, record_id: str):
            assert record_id  # sanity
            self.open_calls += 1
            return io.BytesIO(self._blob)

        def get(self, _record_id: str):
            raise AssertionError("get() should not be used when open_stream is available")

    meta = Meta()
    evidence_id = "run_1/evidence.capture.frame/0"
    meta.put_new(
        evidence_id,
        {
            "schema_version": 1,
            "record_type": "evidence.capture.frame",
            "run_id": "run_1",
            "ts_utc": "2026-02-09T00:00:00Z",
            "content_hash": "deadbeef",
        },
    )
    media = Media(b"x" * (2 * 1024 * 1024))
    out = tmp_path / "bundle.zip"
    ledger = tmp_path / "ledger.ndjson"
    anchors = tmp_path / "anchors.ndjson"
    ledger.write_text("", encoding="utf-8")
    anchors.write_text("", encoding="utf-8")

    report = export_proof_bundle(
        metadata=meta,
        media=media,
        keyring=None,
        ledger_path=ledger,
        anchor_path=anchors,
        output_path=out,
        evidence_ids=[evidence_id],
        citations=None,
    )
    assert report.ok
    assert media.open_calls == 1

