from __future__ import annotations

from typing import Any


class _MemMedia:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def put_new(self, record_id: str, data: bytes, *, ts_utc: str | None = None, fsync_policy: str | None = None) -> None:
        if record_id in self.blobs:
            raise FileExistsError(record_id)
        self.blobs[record_id] = bytes(data)


class _MemMeta:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def put_new(self, record_id: str, value: Any) -> None:
        if record_id in self.rows:
            raise FileExistsError(record_id)
        assert isinstance(value, dict)
        self.rows[record_id] = dict(value)


class _EventBuilder:
    def policy_snapshot_hash(self) -> str:
        return "policyhash"

    def journal_event(self, *_a, **_k) -> str:
        return "evt"

    def ledger_entry(self, *_a, **_k) -> str:
        return "led"


class _Logger:
    def log(self, *_a, **_k) -> None:
        return


def test_drain_overflow_spooled_raw_rgb_converts_to_png() -> None:
    # Import the drain helper from the plugin module (kept deterministic).
    from plugins.builtin.capture_screenshot_windows.plugin import _drain_overflow_item

    media = _MemMedia()
    meta = _MemMeta()
    builder = _EventBuilder()
    logger = _Logger()

    record_id = "run/frame/123"
    # 2x2 RGB: red, green, blue, white
    blob = bytes(
        [
            255,
            0,
            0,
            0,
            255,
            0,
            0,
            0,
            255,
            255,
            255,
            255,
        ]
    )
    payload = {
        "record_type": "spool.capture.screenshot.v1",
        "run_id": "run",
        "ts_utc": "2026-02-09T00:00:00Z",
        "width": 2,
        "height": 2,
        "pixel_format": "RGB",
        "backend": "mss",
        "monitor_index": 0,
        "dedupe": {"fingerprint": "fp"},
        "png_level": 0,
    }
    meta_record = {"record_id": record_id, "payload": payload}

    ok = _drain_overflow_item(
        meta_record,
        blob,
        storage_media=media,
        storage_meta=meta,
        event_builder=builder,
        logger=logger,
    )
    assert ok is True
    assert record_id in media.blobs
    assert media.blobs[record_id].startswith(b"\x89PNG\r\n\x1a\n")
    assert record_id in meta.rows
    assert meta.rows[record_id]["record_type"] == "evidence.capture.frame"
    assert meta.rows[record_id]["encoding"] == "png"

