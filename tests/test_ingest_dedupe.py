from __future__ import annotations

import tempfile

import pytest

from autocapture_nx.ingest.file_ingest import ingest_file
from plugins.builtin.storage_memory.plugin import InMemoryStore


class _MetaStore(InMemoryStore):
    # Provide put_replace for compatibility with SQLite stores.
    def put_replace(self, key: str, value, *, ts_utc=None) -> None:
        self.put(key, value, ts_utc=ts_utc)


def test_ingest_file_dedupes_by_sha256() -> None:
    media = InMemoryStore()
    meta = _MetaStore()
    with tempfile.NamedTemporaryFile(prefix="acp_ingest_", delete=False) as tmp:
        tmp.write(b"hello world\n")
        tmp.flush()
        path = tmp.name

    res1 = ingest_file(
        path=path,
        storage_media=media,
        storage_meta=meta,
        ts_utc="t0",
        run_id="run1",
        event_builder=None,
    )
    res2 = ingest_file(
        path=path,
        storage_media=media,
        storage_meta=meta,
        ts_utc="t1",
        run_id="run1",
        event_builder=None,
    )

    assert res1.input_id == res2.input_id
    assert res1.sha256 == res2.sha256
    assert res1.media_record_id == res2.media_record_id
    assert res1.deduped is False
    assert res2.deduped is True

    # Blob written once.
    assert media.keys().count(res1.media_record_id) == 1
    # Metadata record present.
    record_id = f"run1/evidence.input.file/{res1.input_id}"
    rec = meta.get(record_id)
    assert rec["sha256"] == res1.sha256
    assert rec["media_record_id"] == res1.media_record_id

