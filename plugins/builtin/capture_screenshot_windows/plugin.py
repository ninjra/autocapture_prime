"""Windows screenshot capture plugin (lossless PNG, hash-based dedupe)."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any

from autocapture_nx.capture.screenshot import ScreenshotDeduper, encode_png
from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.kernel.telemetry import record_telemetry
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.windows.win_capture import list_monitors
from autocapture_nx.windows.win_cursor import current_cursor, cursor_shape, CursorShape


class ScreenshotCaptureWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seq = 0
        self._cursor_shape: CursorShape | None = None
        self._cursor_handle: int | None = None

    def capabilities(self) -> dict[str, Any]:
        return {"capture.screenshot": self}

    def start(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Screenshot capture supported on Windows only")
        cfg = self.context.config.get("capture", {}).get("screenshot", {})
        if not bool(cfg.get("enabled", False)):
            return
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
        ensure_run_id(self.context.config)
        storage_media = self.context.get_capability("storage.media")
        storage_meta = self.context.get_capability("storage.metadata")
        event_builder = self.context.get_capability("event.builder")
        logger = self.context.get_capability("observability.logger")
        window_tracker = _optional_capability(self.context, "window.metadata")
        input_tracker = _optional_capability(self.context, "tracking.input")

        cfg = self.context.config.get("capture", {}).get("screenshot", {})
        fps_target = int(cfg.get("fps_target", 2))
        monitor_index = int(cfg.get("monitor_index", 0))
        resolution = str(cfg.get("resolution", "native") or "native")
        backend = str(cfg.get("backend", "mss") or "mss").lower()
        include_cursor = bool(cfg.get("include_cursor", True))
        include_shape = bool(cfg.get("include_cursor_shape", True))
        png_level = int(cfg.get("png_compress_level", 3))
        dedupe_cfg = cfg.get("dedupe", {}) if isinstance(cfg.get("dedupe", {}), dict) else {}
        deduper = ScreenshotDeduper(
            enabled=bool(dedupe_cfg.get("enabled", True)),
            hash_algo=str(dedupe_cfg.get("hash", "blake2b") or "blake2b"),
            sample_bytes=int(dedupe_cfg.get("sample_bytes", 0) or 0),
            force_interval_s=float(dedupe_cfg.get("force_interval_s", 0) or 0),
        )
        monitor_layout = _monitor_layout()
        run_id = str(self.context.config.get("runtime", {}).get("run_id", "run"))
        last_emit = 0.0
        seen_frames = 0
        saved_frames = 0
        last_input_ts: float | None = None

        if backend != "mss":
            logger.log("screenshot.backend_fallback", {"requested": backend, "used": "mss"})

        try:
            import mss
            from PIL import Image
        except Exception as exc:
            raise RuntimeError(f"Missing screenshot dependencies: {exc}") from exc

        with mss.mss() as sct:
            monitors = sct.monitors
            idx = int(monitor_index)
            if idx < 0 or idx >= len(monitors):
                idx = 0
            monitor = monitors[idx]
            mon_left = int(monitor.get("left", 0))
            mon_top = int(monitor.get("top", 0))
            target_size = _parse_resolution(resolution)
            while not self._stop.is_set():
                loop_start = time.monotonic()
                ts_utc = _iso_utc()
                try:
                    raw = sct.grab(monitor)
                except Exception as exc:
                    event_builder.failure_event(
                        "capture.screenshot_failed",
                        stage="capture",
                        error=exc,
                        inputs=[],
                        outputs=[],
                        payload={"backend": "mss"},
                        ts_utc=ts_utc,
                        retryable=True,
                    )
                    _sleep_interval(loop_start, fps_target)
                    continue
                img = Image.frombytes("RGB", raw.size, raw.rgb)
                if target_size and (img.width, img.height) != target_size:
                    img = img.resize(target_size)
                cursor_payload = None
                if include_cursor:
                    cursor_info = current_cursor()
                    if cursor_info is not None:
                        cursor_payload = {
                            "x": int(cursor_info.x),
                            "y": int(cursor_info.y),
                            "visible": bool(cursor_info.visible),
                        }
                        if include_shape:
                            cursor_payload["handle"] = int(cursor_info.handle)
                        if cursor_info.visible and include_shape:
                            shape = self._cursor_shape_cached(cursor_info.handle)
                            if shape is not None:
                                offset_x = int(cursor_info.x) - mon_left
                                offset_y = int(cursor_info.y) - mon_top
                                if target_size and raw.size != target_size:
                                    scale_x = target_size[0] / raw.size[0]
                                    scale_y = target_size[1] / raw.size[1]
                                    offset_x = int(offset_x * scale_x)
                                    offset_y = int(offset_y * scale_y)
                                    hotspot_x = int(shape.hotspot_x * scale_x)
                                    hotspot_y = int(shape.hotspot_y * scale_y)
                                    cursor_img = shape.image.resize(
                                        (int(shape.width * scale_x), int(shape.height * scale_y))
                                    )
                                else:
                                    hotspot_x = shape.hotspot_x
                                    hotspot_y = shape.hotspot_y
                                    cursor_img = shape.image
                                pos = (offset_x - hotspot_x, offset_y - hotspot_y)
                                img.paste(cursor_img, pos, cursor_img)

                raw_bytes = img.tobytes()
                pixel_hash = hashlib.sha256(raw_bytes).hexdigest()
                fingerprint = deduper.fingerprint(raw_bytes)
                now = time.monotonic()
                input_recent = False
                if input_tracker is not None and hasattr(input_tracker, "last_event_ts"):
                    try:
                        current_input_ts = input_tracker.last_event_ts()
                    except Exception:
                        current_input_ts = None
                    if current_input_ts is not None and current_input_ts != last_input_ts:
                        last_input_ts = current_input_ts
                        input_recent = True
                should_store, duplicate = deduper.should_store(fingerprint, now=now)
                seen_frames += 1
                if now - last_emit >= max(0.5, 1.0 / max(1, fps_target)):
                    telemetry = {
                        "ts_utc": ts_utc,
                        "record_id": None,
                        "record_type": "evidence.capture.frame",
                        "output_bytes": 0,
                        "stored": False,
                        "duplicate": bool(duplicate),
                        "seen_frames": int(seen_frames),
                        "saved_frames": int(saved_frames),
                        "fps_target": int(fps_target),
                        "backend": "mss",
                    }
                    record_telemetry("capture.screenshot", telemetry)
                    record_telemetry(f"plugin.{self.plugin_id}", telemetry)
                    last_emit = now
                if not should_store:
                    _sleep_interval(loop_start, fps_target, force_immediate=input_recent)
                    continue
                try:
                    encode_start = time.perf_counter()
                    png_bytes = encode_png(img, compress_level=png_level)
                    encode_ms = int(max(0.0, (time.perf_counter() - encode_start) * 1000.0))
                    record_id = prefixed_id(run_id, "frame", self._seq)
                    write_start = time.perf_counter()
                    if hasattr(storage_media, "put_new"):
                        storage_media.put_new(record_id, png_bytes, ts_utc=ts_utc)
                    else:
                        storage_media.put(record_id, png_bytes, ts_utc=ts_utc)
                    write_ms = int(max(0.0, (time.perf_counter() - write_start) * 1000.0))
                    content_hash = hashlib.sha256(png_bytes).hexdigest()
                    payload = {
                        "record_type": "evidence.capture.frame",
                        "run_id": run_id,
                        "ts_utc": ts_utc,
                        "width": int(img.width),
                        "height": int(img.height),
                        "resolution": f"{int(img.width)}x{int(img.height)}",
                        "encoding": "png",
                        "content_type": "image/png",
                        "content_size": int(len(png_bytes)),
                        "pixel_hash": pixel_hash,
                        "pixel_hash_algo": "sha256",
                        "pixel_size": int(len(raw_bytes)),
                        "lossless": True,
                        "backend": "mss",
                        "monitor_index": int(idx),
                        "dedupe": {
                            "enabled": bool(deduper.enabled),
                            "hash": str(deduper.hash_algo),
                            "sample_bytes": int(deduper.sample_bytes),
                            "force_interval_s": float(deduper.force_interval_s),
                            "duplicate": bool(duplicate),
                            "fingerprint": fingerprint,
                        },
                        "content_hash": content_hash,
                        "policy_snapshot_hash": event_builder.policy_snapshot_hash(),
                        "encode_ms": int(encode_ms),
                        "write_ms": int(write_ms),
                    }
                    if cursor_payload:
                        payload["cursor"] = cursor_payload
                    if monitor_layout:
                        payload["monitor_layout"] = monitor_layout
                        for entry in monitor_layout:
                            if int(entry.get("index", -1)) == int(idx):
                                payload["monitor"] = entry
                                break
                    window_ref = _snapshot_window(window_tracker)
                    if window_ref:
                        payload["window_ref"] = window_ref
                    input_ref = _snapshot_input(input_tracker)
                    if input_ref:
                        payload["input_ref"] = input_ref
                    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
                    if hasattr(storage_meta, "put_new"):
                        storage_meta.put_new(record_id, payload)
                    else:
                        storage_meta.put(record_id, payload)
                    event_builder.journal_event("capture.frame", payload, event_id=record_id, ts_utc=ts_utc)
                    event_builder.ledger_entry(
                        "capture.frame",
                        inputs=[],
                        outputs=[record_id],
                        payload=payload,
                        entry_id=record_id,
                        ts_utc=ts_utc,
                    )
                    deduper.mark_saved(fingerprint, now=now)
                    saved_frames += 1
                    telemetry = {
                        "ts_utc": ts_utc,
                        "record_id": record_id,
                        "record_type": "evidence.capture.frame",
                        "output_bytes": int(len(png_bytes)),
                        "stored": True,
                        "duplicate": bool(duplicate),
                        "seen_frames": int(seen_frames),
                        "saved_frames": int(saved_frames),
                        "fps_target": int(fps_target),
                        "encode_ms": int(encode_ms),
                        "write_ms": int(write_ms),
                        "backend": "mss",
                    }
                    record_telemetry("capture.screenshot", telemetry)
                    record_telemetry(f"plugin.{self.plugin_id}", telemetry)
                    last_emit = now
                    self._seq += 1
                except Exception as exc:
                    event_builder.failure_event(
                        "capture.screenshot_write_failed",
                        stage="storage.write",
                        error=exc,
                        inputs=[],
                        outputs=[],
                        payload={"backend": "mss"},
                        ts_utc=ts_utc,
                        retryable=False,
                    )
                _sleep_interval(loop_start, fps_target, force_immediate=input_recent)

    def _cursor_shape_cached(self, handle: int) -> CursorShape | None:
        if not handle:
            return None
        if self._cursor_handle != handle or self._cursor_shape is None:
            self._cursor_handle = handle
            self._cursor_shape = cursor_shape(handle)
        return self._cursor_shape


def _optional_capability(context: PluginContext, name: str) -> Any | None:
    try:
        return context.get_capability(name)
    except Exception:
        return None


def _iso_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _parse_resolution(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    text = str(value).strip().lower()
    if not text or text == "native":
        return None
    if "x" not in text:
        return None
    left, right = text.split("x", 1)
    try:
        w = int(left)
        h = int(right)
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return (w, h)


def _monitor_layout() -> list[dict[str, int | bool]] | None:
    try:
        return list_monitors()
    except Exception:
        return None


def _snapshot_window(window_tracker: Any | None) -> dict[str, Any] | None:
    if window_tracker is None:
        return None
    if hasattr(window_tracker, "last_record"):
        return window_tracker.last_record()
    if hasattr(window_tracker, "current"):
        payload = window_tracker.current() or {}
        return payload if payload else None
    return None


def _snapshot_input(input_tracker: Any | None) -> dict[str, Any] | None:
    if input_tracker is None:
        return None
    if hasattr(input_tracker, "snapshot"):
        return input_tracker.snapshot(reset=True)
    if hasattr(input_tracker, "last_event_ts"):
        return {"last_event_ts": input_tracker.last_event_ts()}
    return None


def _sleep_interval(start: float, fps_target: int, *, force_immediate: bool = False) -> None:
    if force_immediate:
        return
    interval = 1.0 / max(1, int(fps_target))
    elapsed = time.monotonic() - start
    if elapsed < interval:
        time.sleep(interval - elapsed)


def create_plugin(plugin_id: str, context: PluginContext) -> ScreenshotCaptureWindows:
    return ScreenshotCaptureWindows(plugin_id, context)
