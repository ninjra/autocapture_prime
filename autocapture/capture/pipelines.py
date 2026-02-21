"""Capture pipelines for MX."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autocapture.capture.models import CaptureSegment
from autocapture.capture.spool import CaptureSpool
from autocapture.core.ids import stable_id
from autocapture.storage.blob_store import BlobStore
from autocapture.storage.keys import load_keyring
from autocapture.config.defaults import default_config_paths
from autocapture.config.load import load_config


class CaptureEncoder:
    def encode(self, payload: bytes) -> bytes:
        return payload


class CapturePipeline:
    def __init__(self, spool: CaptureSpool, blob_store: BlobStore, encoder: CaptureEncoder) -> None:
        self._spool = spool
        self._blob_store = blob_store
        self._encoder = encoder

    def capture_bytes(self, payload: bytes, metadata: dict[str, Any] | None = None) -> CaptureSegment:
        metadata = metadata or {}
        encoded = self._encoder.encode(payload)
        blob_id = self._blob_store.put(encoded)
        ts_utc = datetime.now(timezone.utc).isoformat()
        segment_id = stable_id("capture.segment", {"ts_utc": ts_utc, "blob_id": blob_id})
        segment = CaptureSegment(segment_id=segment_id, ts_utc=ts_utc, blob_id=blob_id, metadata=metadata)
        if not self._spool.append(segment):
            raise RuntimeError(f"capture_spool_write_failed:{segment.segment_id}")
        return segment


def create_capture_source(plugin_id: str) -> CapturePipeline:
    config = load_config(default_config_paths(), safe_mode=False)
    spool_dir = config.get("storage", {}).get("spool_dir", "data/spool")
    spool_fsync = bool(config.get("storage", {}).get("spool_fsync", True))
    spool = CaptureSpool(spool_dir, fsync=spool_fsync)
    blob_root = config.get("storage", {}).get("blob_dir", "data/blobs")
    blob_store = BlobStore(blob_root, load_keyring(config))
    encoder = CaptureEncoder()
    return CapturePipeline(spool, blob_store, encoder)


def create_capture_encoder(plugin_id: str) -> CaptureEncoder:
    return CaptureEncoder()
