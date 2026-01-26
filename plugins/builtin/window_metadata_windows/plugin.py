"""Windows window metadata plugin."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.windows.win_window import active_window


class WindowMetadataWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_info: dict[str, Any] | None = None
        self._last_record_id: str | None = None
        self._last_ts_utc: str | None = None
        self._lock = threading.Lock()

    def capabilities(self) -> dict[str, Any]:
        return {"window.metadata": self}

    def current(self) -> dict[str, Any] | None:
        return self._last_info

    def last_record(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._last_record_id:
                return None
            payload = {
                "record_id": self._last_record_id,
                "ts_utc": self._last_ts_utc,
            }
            if self._last_info:
                payload["window"] = dict(self._last_info)
            return payload

    def start(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Window metadata capture supported on Windows only")
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        event_builder = self.context.get_capability("event.builder")
        metadata_store = self.context.get_capability("storage.metadata")
        window_cfg = self.context.config.get("capture", {}).get("window_metadata", {})
        sample_hz = int(window_cfg.get("sample_hz", 5))
        interval = 1.0 / max(sample_hz, 1)
        seq = 0
        run_id = ensure_run_id(self.context.config)
        last_hwnd = None
        while not self._stop.is_set():
            info = active_window()
            if info and info.hwnd != last_hwnd:
                ts = datetime.now(timezone.utc).isoformat()
                payload = {
                    "title": info.title,
                    "process_path": info.process_path,
                    "hwnd": info.hwnd,
                    "rect": [int(value) for value in info.rect],
                }
                record_id = prefixed_id(run_id, "window", seq)
                event_builder.journal_event(
                    "window.meta",
                    payload,
                    event_id=record_id,
                    ts_utc=ts,
                )
                metadata_store.put(
                    record_id,
                    {
                        "record_type": "evidence.window.meta",
                        "ts_utc": ts,
                        "text": f"{info.title} {info.process_path}".strip(),
                        "window": payload,
                    },
                )
                seq += 1
                last_hwnd = info.hwnd
                with self._lock:
                    self._last_info = payload
                    self._last_record_id = record_id
                    self._last_ts_utc = ts
            time.sleep(interval)


def create_plugin(plugin_id: str, context: PluginContext) -> WindowMetadataWindows:
    return WindowMetadataWindows(plugin_id, context)
