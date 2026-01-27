"""Windows input tracking plugin using pynput."""

from __future__ import annotations

import os
import threading
from collections import deque
import time
import math
from datetime import datetime, timezone
from typing import Any

import json
import hashlib
import struct

from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class InputTrackerWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._listener = None
        self._last_event_ts = None
        self._last_event_id = None
        self._last_event_ts_utc = None
        self._counts = {"key": 0, "mouse": 0}
        self._last_cursor: dict[str, int] | None = None
        self._lock = threading.Lock()
        self._batcher = _InputBatcher()
        self._flush_thread: threading.Thread | None = None
        self._flush_interval_ms = 250
        self._event_builder = None
        self._batch_seq = 0
        self._activity_events: deque[float] = deque(maxlen=128)

    def capabilities(self) -> dict[str, Any]:
        return {"tracking.input": self}

    def last_event_ts(self) -> float | None:
        return self._last_event_ts

    def idle_seconds(self) -> float:
        if self._last_event_ts is None:
            return float("inf")
        return max(0.0, time.time() - self._last_event_ts)

    def snapshot(self, reset: bool = False) -> dict[str, Any]:
        with self._lock:
            payload = {
                "counts": dict(self._counts),
                "last_event_id": self._last_event_id,
                "last_ts_utc": self._last_event_ts_utc,
            }
            if self._last_cursor:
                payload["cursor"] = dict(self._last_cursor)
            if reset:
                self._counts = {"key": 0, "mouse": 0}
            return payload

    def activity_signal(self) -> dict[str, Any]:
        active_window_s = float(self.context.config.get("runtime", {}).get("active_window_s", 3))
        window_s = max(5.0, active_window_s * 3.0)
        now = time.time()
        idle = self.idle_seconds()
        with self._lock:
            cutoff = now - window_s
            while self._activity_events and self._activity_events[0] < cutoff:
                self._activity_events.popleft()
            events = list(self._activity_events)
            last_event_ts = self._last_event_ts
        rate_hz = (len(events) / window_s) if window_s > 0 else 0.0
        if idle == float("inf"):
            freshness = 0.0
        else:
            freshness = math.exp(-max(0.0, idle) / max(0.5, active_window_s))
        target_rate = max(0.5, 6.0 / window_s)
        rate_score = min(1.0, rate_hz / target_rate) if target_rate > 0 else 0.0
        score = max(freshness, rate_score)
        user_active = idle < active_window_s if idle != float("inf") else False
        return {
            "idle_seconds": idle,
            "user_active": user_active,
            "activity_score": score,
            "event_rate_hz": rate_hz,
            "recent_activity": bool(events),
            "last_event_ts": last_event_ts,
        }

    def start(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Input tracking supported on Windows only")
        try:
            from pynput import keyboard, mouse
        except Exception as exc:
            raise RuntimeError(f"Missing input dependency: {exc}")

        self._stop.clear()
        self._batcher = _InputBatcher()
        event_builder = self.context.get_capability("event.builder")
        self._event_builder = event_builder
        capture_cfg = self.context.config.get("capture", {}).get("input_tracking", {})
        mode = capture_cfg.get("mode", "raw")
        self._flush_interval_ms = int(capture_cfg.get("flush_interval_ms", 250))
        if mode == "off":
            return

        def on_key_press(key):
            ts = datetime.now(timezone.utc).isoformat()
            payload = {"action": "press"}
            if mode == "raw":
                payload["key"] = str(key)
            self._record_event("key", payload, ts)

        def on_click(x, y, button, pressed):
            ts = datetime.now(timezone.utc).isoformat()
            payload = {"button": str(button), "pressed": pressed}
            if mode == "raw":
                payload["x"] = int(x)
                payload["y"] = int(y)
            self._record_event("mouse", payload, ts)
            with self._lock:
                if "x" in payload and "y" in payload:
                    self._last_cursor = {"x": int(payload["x"]), "y": int(payload["y"])}

        self._listener = {
            "keyboard": keyboard.Listener(on_press=on_key_press),
            "mouse": mouse.Listener(on_click=on_click),
        }
        self._listener["keyboard"].start()
        self._listener["mouse"].start()
        self._last_event_ts = time.time()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def stop(self) -> None:
        if self._listener:
            self._listener["keyboard"].stop()
            self._listener["mouse"].stop()
            self._listener = None
        self._stop.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=5)
        self._flush_batch()

    def _record_event(self, kind: str, payload: dict[str, Any], ts_utc: str) -> None:
        event = {"kind": kind, "ts_utc": ts_utc, **payload}
        with self._lock:
            self._batcher.add(event)
            if kind in self._counts:
                self._counts[kind] += 1
            self._last_event_ts = time.time()
            self._last_event_ts_utc = ts_utc
            self._activity_events.append(self._last_event_ts)

    def _flush_loop(self) -> None:
        interval_s = max(0.05, self._flush_interval_ms / 1000.0)
        while not self._stop.is_set():
            time.sleep(interval_s)
            self._flush_batch()

    def _flush_batch(self) -> None:
        event_builder = self._event_builder
        if event_builder is None:
            return
        with self._lock:
            events, start_ts, end_ts = self._batcher.drain()
        if not events:
            return
        payload = {
            "start_ts_utc": start_ts,
            "end_ts_utc": end_ts,
            "events": events,
            "counts": {
                "key": sum(1 for event in events if event.get("kind") == "key"),
                "mouse": sum(1 for event in events if event.get("kind") == "mouse"),
            },
        }
        event_id = event_builder.journal_event("input.batch", payload, ts_utc=end_ts)
        with self._lock:
            self._last_event_id = event_id
        capture_cfg = self.context.config.get("capture", {}).get("input_tracking", {})
        store_derived = bool(capture_cfg.get("store_derived", True))
        if not store_derived:
            return
        try:
            storage_media = self.context.get_capability("storage.media")
            storage_meta = self.context.get_capability("storage.metadata")
        except Exception:
            return
        if storage_media is None or storage_meta is None:
            return
        run_id = ensure_run_id(self.context.config)
        seq = self._batch_seq
        self._batch_seq += 1
        log_id = prefixed_id(run_id, "derived.input.log", seq)
        summary_id = prefixed_id(run_id, "derived.input.summary", seq)
        encoded = _encode_input_log(events)
        if hasattr(storage_media, "put_new"):
            storage_media.put_new(log_id, encoded, ts_utc=end_ts)
        else:
            storage_media.put(log_id, encoded, ts_utc=end_ts)
        content_hash = hashlib.sha256(encoded).hexdigest()
        summary = {
            "record_type": "derived.input.summary",
            "run_id": run_id,
            "ts_utc": end_ts,
            "start_ts_utc": start_ts,
            "end_ts_utc": end_ts,
            "log_id": log_id,
            "event_id": event_id,
            "event_count": int(len(events)),
            "counts": payload["counts"],
            "content_hash": content_hash,
        }
        if hasattr(storage_meta, "put_new"):
            storage_meta.put_new(summary_id, summary)
        else:
            storage_meta.put(summary_id, summary)
        event_builder.ledger_entry(
            "input.batch",
            inputs=[event_id],
            outputs=[log_id, summary_id],
            payload=summary,
            entry_id=summary_id,
            ts_utc=end_ts,
        )


def create_plugin(plugin_id: str, context: PluginContext) -> InputTrackerWindows:
    return InputTrackerWindows(plugin_id, context)


class _InputBatcher:
    def __init__(self) -> None:
        self._events: deque[dict[str, Any]] = deque()
        self._first_ts: str | None = None
        self._last_ts: str | None = None

    def add(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        ts = str(event.get("ts_utc", ""))
        if self._first_ts is None:
            self._first_ts = ts
        self._last_ts = ts

    def drain(self) -> tuple[list[dict[str, Any]], str | None, str | None]:
        events = list(self._events)
        self._events.clear()
        start = self._first_ts
        end = self._last_ts
        self._first_ts = None
        self._last_ts = None
        return events, start, end


def _encode_input_log(events: list[dict[str, Any]]) -> bytes:
    payload = bytearray(b"INPT1")
    for event in events:
        data = json.dumps(event, sort_keys=True).encode("utf-8")
        payload.extend(struct.pack(">I", len(data)))
        payload.extend(data)
    return bytes(payload)
