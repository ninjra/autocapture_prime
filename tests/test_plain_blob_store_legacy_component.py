from __future__ import annotations

import tempfile
from pathlib import Path

from autocapture_nx.kernel.ids import encode_record_id_component
from plugins.builtin.storage_sqlcipher.plugin import PlainBlobStore


def test_plain_blob_store_reads_legacy_component_encoded_blob_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "media"
        store = PlainBlobStore(str(root), run_id="run_new", fsync_policy="none")
        record_id = "run_20260220T023853Z_63728/evidence.capture.frame/1771604304713"

        legacy_encoded = encode_record_id_component(record_id)
        path = root / f"{legacy_encoded}.blob"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"\x89PNG\r\n\x1a\nlegacy"
        path.write_bytes(payload)

        assert store.get(record_id) == payload

