"""Clipboard capture plugin (Windows)."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


_CF_UNICODETEXT = 13


def _read_clipboard_text() -> tuple[str | None, str | None]:
    if os.name != "nt":
        return None, None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE

        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL

        if not user32.OpenClipboard(None):
            return None, None
        try:
            if not user32.IsClipboardFormatAvailable(_CF_UNICODETEXT):
                return None, None
            handle = user32.GetClipboardData(_CF_UNICODETEXT)
            if not handle:
                return None, None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None, None
            try:
                text = ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
            return text, "text/plain"
        finally:
            user32.CloseClipboard()
    except Exception:
        return None, None


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        raw = str(pattern).strip()
        if not raw:
            continue
        try:
            compiled.append(re.compile(raw))
        except re.error:
            continue
    return compiled


def _apply_redaction(text: str, patterns: list[re.Pattern[str]], action: str) -> tuple[str | None, bool]:
    if not patterns:
        return text, False
    for pattern in patterns:
        if pattern.search(text):
            if action == "drop":
                return None, True
            return "[REDACTED]", True
    return text, False


class ClipboardCaptureWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seq = 0
        self._last_hash: str | None = None
        self._lock = threading.Lock()
        self._reader = _read_clipboard_text
        self._redact_patterns: list[re.Pattern[str]] = []
        self._redact_action = "mask"

    def capabilities(self) -> dict[str, Any]:
        return {"tracking.clipboard": self}

    def start(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Clipboard capture supported on Windows only")
        cfg = self.context.config.get("capture", {}).get("clipboard", {})
        if not bool(cfg.get("enabled", False)):
            return
        self._stop.clear()
        self._configure_redaction(cfg)
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def capture_once(self) -> None:
        self._capture()

    def _configure_redaction(self, cfg: dict[str, Any]) -> None:
        redact_cfg = cfg.get("redact", {}) if isinstance(cfg, dict) else {}
        patterns = redact_cfg.get("patterns", []) if isinstance(redact_cfg, dict) else []
        action = str(redact_cfg.get("action", "mask") if isinstance(redact_cfg, dict) else "mask").lower()
        if action not in {"mask", "drop"}:
            action = "mask"
        self._redact_patterns = _compile_patterns([str(item) for item in patterns if str(item).strip()])
        self._redact_action = action

    def _run_loop(self) -> None:
        cfg = self.context.config.get("capture", {}).get("clipboard", {})
        poll = float(cfg.get("poll_interval_s", 0.5))
        poll = max(0.1, min(poll, 5.0))
        while not self._stop.is_set():
            self._capture()
            time.sleep(poll)

    def _capture(self) -> None:
        cfg = self.context.config.get("capture", {}).get("clipboard", {})
        max_bytes = int(cfg.get("max_bytes", 200000))
        text, content_type = self._reader()
        if text is None:
            return
        if not content_type:
            content_type = "text/plain"
        raw = text.encode("utf-8", errors="ignore")
        truncated = False
        if max_bytes > 0 and len(raw) > max_bytes:
            raw = raw[:max_bytes]
            text = raw.decode("utf-8", errors="ignore")
            truncated = True
        redacted = False
        if self._redact_patterns:
            redacted_text, redacted = _apply_redaction(text, self._redact_patterns, self._redact_action)
            if redacted_text is None:
                return
            text = redacted_text
            raw = text.encode("utf-8", errors="ignore")
        content_hash = hashlib.sha256(raw).hexdigest()
        with self._lock:
            if self._last_hash == content_hash:
                return
            seq = self._seq
            self._seq += 1
        run_id = ensure_run_id(self.context.config)
        ts_utc = datetime.now(timezone.utc).isoformat()
        record_id = prefixed_id(run_id, "clipboard", seq)
        payload = {
            "record_type": "evidence.clipboard.item",
            "run_id": run_id,
            "ts_utc": ts_utc,
            "content_type": content_type,
            "content_size": int(len(raw)),
            "source": "clipboard",
            "redacted": bool(redacted),
            "truncated": bool(truncated),
            "content_hash": content_hash,
        }
        payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
        try:
            storage_media = self.context.get_capability("storage.media")
            storage_meta = self.context.get_capability("storage.metadata")
            event_builder = self.context.get_capability("event.builder")
        except Exception:
            return
        if storage_media is None or storage_meta is None:
            return
        if hasattr(storage_media, "put_new"):
            storage_media.put_new(record_id, raw, ts_utc=ts_utc)
        else:
            storage_media.put(record_id, raw, ts_utc=ts_utc)
        if hasattr(storage_meta, "put_new"):
            storage_meta.put_new(record_id, payload)
        else:
            storage_meta.put(record_id, payload)
        if event_builder is not None:
            event_builder.journal_event("clipboard.capture", payload, event_id=record_id, ts_utc=ts_utc)
            event_builder.ledger_entry(
                "clipboard.capture",
                inputs=[],
                outputs=[record_id],
                payload=payload,
                entry_id=record_id,
                ts_utc=ts_utc,
            )
        with self._lock:
            self._last_hash = content_hash


def create_plugin(plugin_id: str, context: PluginContext) -> ClipboardCaptureWindows:
    return ClipboardCaptureWindows(plugin_id, context)
