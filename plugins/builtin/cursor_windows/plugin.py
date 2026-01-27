"""Windows cursor timeline capture plugin."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.windows.win_cursor import current_cursor


class CursorTimelineWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_cursor: dict[str, Any] | None = None
        self._last_record_id: str | None = None
        self._last_ts_utc: str | None = None
        self._lock = threading.Lock()
        self._seq = 0

    def capabilities(self) -> dict[str, Any]:
        return {"tracking.cursor": self}

    def start(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Cursor capture supported on Windows only")
        if self._thread and self._thread.is_alive():
            return
        cfg = self.context.config.get("capture", {}).get("cursor", {})
        if not bool(cfg.get("enabled", False)):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def last_record(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._last_record_id:
                return None
            payload: dict[str, Any] = {
                "record_id": self._last_record_id,
                "ts_utc": self._last_ts_utc,
            }
            if self._last_cursor:
                payload["cursor"] = dict(self._last_cursor)
            return payload

    def _run_loop(self) -> None:
        cfg = self.context.config.get("capture", {}).get("cursor", {})
        include_shape = bool(cfg.get("include_shape", True))
        sample_hz = int(cfg.get("sample_hz", 5))
        interval = 1.0 / max(1, sample_hz)
        run_id = ensure_run_id(self.context.config)
        event_builder = self.context.get_capability("event.builder")
        metadata = self.context.get_capability("storage.metadata")
        while not self._stop.is_set():
            cursor = current_cursor()
            if cursor is None:
                time.sleep(interval)
                continue
            ts_utc = datetime.now(timezone.utc).isoformat()
            record_id, payload = _cursor_record(
                run_id,
                self._seq,
                cursor,
                ts_utc=ts_utc,
                include_shape=include_shape,
                sample_hz=sample_hz,
            )
            if payload.get("cursor") == self._last_cursor:
                time.sleep(interval)
                continue
            if hasattr(metadata, "put_new"):
                try:
                    metadata.put_new(record_id, payload)
                except Exception:
                    time.sleep(interval)
                    continue
            else:
                metadata.put(record_id, payload)
            event_builder.journal_event("cursor.sample", payload, event_id=record_id, ts_utc=ts_utc)
            event_builder.ledger_entry(
                "cursor.sample",
                inputs=[],
                outputs=[record_id],
                payload=payload,
                entry_id=record_id,
                ts_utc=ts_utc,
            )
            with self._lock:
                self._last_cursor = payload.get("cursor")
                self._last_record_id = record_id
                self._last_ts_utc = ts_utc
            self._seq += 1
            time.sleep(interval)


def create_plugin(plugin_id: str, context: PluginContext) -> CursorTimelineWindows:
    return CursorTimelineWindows(plugin_id, context)


def _cursor_payload(cursor: Any, *, include_shape: bool) -> dict[str, Any]:
    payload = {
        "x": int(getattr(cursor, "x", 0)),
        "y": int(getattr(cursor, "y", 0)),
        "visible": bool(getattr(cursor, "visible", True)),
    }
    if include_shape:
        payload["handle"] = int(getattr(cursor, "handle", 0))
    return payload


def _cursor_record(
    run_id: str,
    seq: int,
    cursor: Any,
    *,
    ts_utc: str,
    include_shape: bool,
    sample_hz: int,
) -> tuple[str, dict[str, Any]]:
    record_id = prefixed_id(run_id, "cursor", seq)
    payload = {
        "record_type": "derived.cursor.sample",
        "run_id": run_id,
        "ts_utc": ts_utc,
        "cursor": _cursor_payload(cursor, include_shape=include_shape),
        "sample_hz": int(sample_hz),
    }
    payload["content_hash"] = sha256_canonical(payload["cursor"])
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    return record_id, payload
