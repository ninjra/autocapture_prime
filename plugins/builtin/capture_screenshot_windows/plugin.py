"""Windows screenshot capture plugin (lossless PNG, hash-based dedupe)."""

from __future__ import annotations

import hashlib
import os
import queue
import threading
import time
from typing import Any

from autocapture_nx.capture.screenshot import ScreenshotDeduper, encode_png
from autocapture_nx.capture.overflow_spool import OverflowSpool, OverflowSpoolConfig
from autocapture_nx.capture.screenshot_policy import schedule_from_config
from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.kernel.telemetry import record_telemetry
from autocapture_nx.storage.retention import evaluate_disk_pressure, should_pause_capture
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.windows.win_capture import list_monitors
from autocapture_nx.windows.win_cursor import current_cursor, cursor_shape, CursorShape


class ScreenshotCaptureWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        # Keep the queue small and block instead of dropping under backpressure.
        # If storage is slower than capture, we prefer slowing capture (no-loss)
        # over silently dropping evidence.
        self._store_queue: "queue.Queue[dict[str, Any] | None]" = queue.Queue(maxsize=2)
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
        try:
            self._store_queue.put_nowait(None)
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=5)
        if self._worker:
            self._worker.join(timeout=5)

    def _run_loop(self) -> None:
        ensure_run_id(self.context.config)
        storage_media = self.context.get_capability("storage.media")
        storage_meta = self.context.get_capability("storage.metadata")
        event_builder = self.context.get_capability("event.builder")
        logger = self.context.get_capability("observability.logger")
        window_tracker = _optional_capability(self.context, "window.metadata")
        input_tracker = _optional_capability(self.context, "tracking.input")

        cfg = self.context.config.get("capture", {}).get("screenshot", {})
        monitor_index = int(cfg.get("monitor_index", 0))
        resolution = str(cfg.get("resolution", "native") or "native")
        backend = str(cfg.get("backend", "mss") or "mss").lower()
        include_cursor = bool(cfg.get("include_cursor", True))
        include_shape = bool(cfg.get("include_cursor_shape", True))
        png_level = int(cfg.get("png_compress_level", 3))
        media_fsync_policy = str(cfg.get("media_fsync_policy", "") or "").strip().lower() or None
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
        last_mode: str | None = None
        render_cursor = bool(cfg.get("render_cursor", cfg.get("include_cursor", True)))

        def _store_worker() -> None:
            last_disk_level: str | None = None
            overflow = OverflowSpool(OverflowSpoolConfig.from_config(self.context.config))
            try:
                overflow.ensure_dirs()
            except Exception:
                overflow = OverflowSpool(OverflowSpoolConfig(enabled=False, root="", drain_interval_s=2.0, max_drain_per_tick=0))
            while not self._stop.is_set():
                # Drain overflow spooled items when the primary data_dir volume has recovered.
                try:
                    decision = evaluate_disk_pressure(self.context.config)
                except Exception:
                    decision = None
                if decision is not None and not should_pause_capture(decision) and overflow.enabled:
                    try:
                        drain_stats = overflow.drain_if_due(now=time.monotonic(), drain_fn=lambda meta, blob: _drain_overflow_item(
                            meta,
                            blob,
                            storage_media=storage_media,
                            storage_meta=storage_meta,
                            event_builder=event_builder,
                            logger=logger,
                        ))
                        if int(drain_stats.get("drained", 0) or 0) > 0:
                            record_telemetry("capture.screenshot.overflow_drained", {"drained": int(drain_stats["drained"]), "pending": int(drain_stats["pending"])})
                    except Exception:
                        pass
                try:
                    job = self._store_queue.get(timeout=0.5)
                except Exception:
                    continue
                if job is None:
                    break
                try:
                    # Fail closed on low disk: do not partially write evidence.
                    try:
                        if decision is None:
                            decision = evaluate_disk_pressure(self.context.config)
                        if decision.level != last_disk_level:
                            last_disk_level = decision.level
                            record_telemetry(
                                "disk.pressure",
                                {
                                    "ts_utc": str(job.get("ts_utc") or ""),
                                    "level": decision.level,
                                    "free_gb": int(decision.free_gb),
                                    "free_bytes": int(decision.free_bytes),
                                    "hard_halt": bool(decision.hard_halt),
                                },
                            )
                        if should_pause_capture(decision):
                            # Primary volume is under hard disk pressure; spool to overflow (if configured).
                            if overflow.enabled:
                                store_start = time.perf_counter()
                                committed = _store_job_overflow(
                                    job,
                                    overflow=overflow,
                                    storage_media=storage_media,
                                    storage_meta=storage_meta,
                                    event_builder=event_builder,
                                    logger=logger,
                                    primary_hard_halt=True,
                                )
                                try:
                                    record_telemetry(
                                        "capture.screenshot.store",
                                        {
                                            "ts_utc": str(job.get("ts_utc") or ""),
                                            "record_id": str(job.get("record_id") or ""),
                                            "store_ms": int(max(0.0, (time.perf_counter() - store_start) * 1000.0)),
                                            "overflow": True,
                                            "committed": bool(committed),
                                        },
                                    )
                                except Exception:
                                    pass
                                continue
                            try:
                                payload = {
                                    "reason": "disk_low",
                                    "level": decision.level,
                                    "free_bytes": int(decision.free_bytes),
                                    "threshold_mb": int(decision.watermark_hard_mb),
                                }
                                event_builder.journal_event("capture.halt_disk", payload, ts_utc=str(job.get("ts_utc") or ""))
                                event_builder.ledger_entry(
                                    "capture.halt_disk",
                                    inputs=[],
                                    outputs=[],
                                    payload={"event": "capture.halt_disk", **payload},
                                    ts_utc=str(job.get("ts_utc") or ""),
                                )
                            except Exception:
                                pass
                            # Stop capture loop. We cannot safely persist evidence.
                            self._stop.set()
                            break
                    except Exception:
                        # Disk sampling is best-effort; do not fail open if it errors.
                        pass
                    store_start = time.perf_counter()
                    committed_primary = _store_job_overflow(
                        job,
                        overflow=overflow,
                        storage_media=storage_media,
                        storage_meta=storage_meta,
                        event_builder=event_builder,
                        logger=logger,
                        primary_hard_halt=False,
                    )
                    # Only mark as saved after the job is persisted. If storage fails,
                    # we prefer re-attempting capture over losing evidence due to
                    # optimistic dedupe state.
                    if committed_primary:
                        try:
                            dedupe_payload = job.get("dedupe") if isinstance(job.get("dedupe"), dict) else {}
                            fingerprint = dedupe_payload.get("fingerprint")
                            if isinstance(fingerprint, str) and fingerprint:
                                deduper.mark_saved(fingerprint, now=time.monotonic())
                        except Exception:
                            pass
                    try:
                        record_telemetry(
                            "capture.screenshot.store",
                            {
                                "ts_utc": str(job.get("ts_utc") or ""),
                                "record_id": str(job.get("record_id") or ""),
                                "store_ms": int(max(0.0, (time.perf_counter() - store_start) * 1000.0)),
                                "committed": bool(committed_primary),
                            },
                        )
                    except Exception:
                        pass
                except Exception:
                    # Keep capture alive even if storage errors occur.
                    pass

        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=_store_worker, daemon=True, name="screenshot-store-worker")
            self._worker.start()

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
                idle_seconds = _idle_seconds(input_tracker)
                schedule = schedule_from_config(cfg, idle_seconds=idle_seconds)
                # Override forced-store behavior based on mode.
                deduper.force_interval_s = float(schedule.force_interval_s)
                if schedule.mode != last_mode:
                    last_mode = schedule.mode
                    try:
                        payload = {
                            "mode": str(schedule.mode),
                            "interval_s": float(schedule.interval_s),
                            "force_interval_s": float(schedule.force_interval_s),
                            "idle_seconds": float(idle_seconds) if idle_seconds is not None else None,
                        }
                        record_telemetry("capture.screenshot.activity", {"ts_utc": ts_utc, **payload})
                        logger.log("capture.screenshot.activity", payload)
                        event_builder.journal_event("capture.screenshot.activity", payload, ts_utc=ts_utc)
                        event_builder.ledger_entry(
                            "capture.screenshot.activity",
                            inputs=[],
                            outputs=[],
                            payload={"event": "capture.screenshot.activity", **payload},
                            ts_utc=ts_utc,
                        )
                    except Exception:
                        pass
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
                    _sleep_for(loop_start, schedule.interval_s)
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
                        if render_cursor and cursor_info.visible and include_shape:
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

                fingerprint = _fingerprint_thumbnail(img, deduper)
                now = time.monotonic()
                should_store, duplicate = deduper.should_store(fingerprint, now=now)
                seen_frames += 1
                interval_s = float(schedule.interval_s)
                # Telemetry-only: avoid reporting "1 fps" when idle interval is 60s.
                fps_target = int(round(1.0 / interval_s)) if interval_s > 0 and interval_s < 10.0 else 0
                if now - last_emit >= max(0.5, float(schedule.interval_s)):
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
                        "interval_s": float(interval_s),
                        "backend": "mss",
                    }
                    record_telemetry("capture.screenshot", telemetry)
                    record_telemetry(f"plugin.{self.plugin_id}", telemetry)
                    last_emit = now
                if not should_store:
                    _sleep_for(loop_start, schedule.interval_s)
                    continue
                try:
                    record_id = prefixed_id(run_id, "frame", self._seq)
                    encode_ms = 0
                    if event_builder is not None and hasattr(event_builder, "capture_stage"):
                        try:
                            event_builder.capture_stage(
                                record_id,
                                "evidence.capture.frame",
                                ts_utc=ts_utc,
                                payload={"backend": "mss", "monitor_index": int(idx)},
                            )
                        except Exception:
                            pass
                    job = {
                        "record_id": record_id,
                        "run_id": run_id,
                        "ts_utc": ts_utc,
                        "monitor_index": int(idx),
                        "backend": "mss",
                        "img": img,
                        "png_level": int(png_level),
                        "cursor_payload": cursor_payload,
                        "monitor_layout": monitor_layout,
                        "window_ref": _snapshot_window(window_tracker),
                        "input_ref": _snapshot_input(input_tracker),
                        "dedupe": {
                            "enabled": bool(deduper.enabled),
                            "hash": str(deduper.hash_algo),
                            "sample_bytes": int(deduper.sample_bytes),
                            "force_interval_s": float(deduper.force_interval_s),
                            "duplicate": bool(duplicate),
                            "fingerprint": fingerprint,
                        },
                        "render_cursor": bool(render_cursor),
                        "media_fsync_policy": media_fsync_policy,
                    }
                    # No-loss policy: never drop frames due to store backpressure.
                    # If storage cannot keep up, block here until the worker drains.
                    enqueue_start = time.perf_counter()
                    while not self._stop.is_set():
                        try:
                            self._store_queue.put(job, timeout=0.5)
                            break
                        except queue.Full:
                            continue
                    try:
                        wait_ms = int(max(0.0, (time.perf_counter() - enqueue_start) * 1000.0))
                        if wait_ms > 0:
                            record_telemetry(
                                "capture.screenshot.backpressure_wait",
                                {"ts_utc": ts_utc, "wait_ms": wait_ms, "mode": str(schedule.mode)},
                            )
                    except Exception:
                        pass

                    saved_frames += 1  # "scheduled to store" counter (actual store metrics emitted by worker)
                    telemetry = {
                        "ts_utc": ts_utc,
                        "record_id": record_id,
                        "record_type": "evidence.capture.frame",
                        "output_bytes": 0,
                        "stored": True,
                        "duplicate": bool(duplicate),
                        "seen_frames": int(seen_frames),
                        "saved_frames": int(saved_frames),
                        "fps_target": int(fps_target),
                        "encode_ms": int(encode_ms),
                        "write_ms": 0,
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
                _sleep_for(loop_start, schedule.interval_s)

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


def _sleep_for(start: float, interval_s: float) -> None:
    interval = float(interval_s)
    if interval <= 0:
        return
    elapsed = time.monotonic() - start
    if elapsed < interval:
        time.sleep(interval - elapsed)


def _idle_seconds(input_tracker: Any | None) -> float | None:
    if input_tracker is None:
        return None
    if hasattr(input_tracker, "activity_signal"):
        try:
            signal = input_tracker.activity_signal()
        except Exception:
            signal = None
        if isinstance(signal, dict) and "idle_seconds" in signal:
            try:
                return float(signal.get("idle_seconds"))
            except Exception:
                return None
    if hasattr(input_tracker, "idle_seconds"):
        try:
            return float(input_tracker.idle_seconds())
        except Exception:
            return None
    return None


def _fingerprint_thumbnail(img: Any, deduper: ScreenshotDeduper) -> str:
    # Keep this deterministic and cheap: resize to a fixed maximum size and hash bytes.
    try:
        from PIL import Image  # type: ignore
    except Exception:
        thumb = img
    else:
        max_w = 96
        max_h = 96
        w = int(getattr(img, "width", 0) or 0)
        h = int(getattr(img, "height", 0) or 0)
        if w > 0 and h > 0:
            scale = min(max_w / w, max_h / h)
            tw = max(1, int(round(w * scale)))
            th = max(1, int(round(h * scale)))
            thumb = img.resize((tw, th), resample=Image.BILINEAR)
        else:
            thumb = img
    try:
        data = thumb.tobytes()
    except Exception:
        try:
            data = bytes(thumb)
        except Exception:
            data = b""
    return deduper.fingerprint(data)


def _store_job(
    job: dict[str, Any],
    *,
    storage_media: Any,
    storage_meta: Any,
    event_builder: Any,
    logger: Any,
) -> None:
    record_id = str(job.get("record_id") or "")
    run_id = str(job.get("run_id") or "")
    ts_utc = str(job.get("ts_utc") or "")
    monitor_index = int(job.get("monitor_index") or 0)
    backend = str(job.get("backend") or "mss")
    img = job.get("img")
    png_level = int(job.get("png_level") or 3)
    cursor_payload = job.get("cursor_payload")
    monitor_layout = job.get("monitor_layout")
    window_ref = job.get("window_ref")
    input_ref = job.get("input_ref")
    dedupe_payload = job.get("dedupe") if isinstance(job.get("dedupe"), dict) else {}
    media_fsync_policy = job.get("media_fsync_policy")

    encode_start = time.perf_counter()
    png_bytes = encode_png(img, compress_level=png_level)
    encode_ms = int(max(0.0, (time.perf_counter() - encode_start) * 1000.0))

    write_start = time.perf_counter()
    if hasattr(storage_media, "put_new"):
        storage_media.put_new(record_id, png_bytes, ts_utc=ts_utc, fsync_policy=media_fsync_policy)
    else:
        storage_media.put(record_id, png_bytes, ts_utc=ts_utc, fsync_policy=media_fsync_policy)
    write_ms = int(max(0.0, (time.perf_counter() - write_start) * 1000.0))

    # Avoid hashing full raw pixel buffers (large + extra copies). For reliability and
    # performance, treat the PNG as the canonical stored representation.
    content_hash = hashlib.sha256(png_bytes).hexdigest()
    pixel_hash = content_hash
    width = int(getattr(img, "width", 0) or 0)
    height = int(getattr(img, "height", 0) or 0)
    pixel_size = int(width * height * 3) if width > 0 and height > 0 else 0
    payload = {
        "record_type": "evidence.capture.frame",
        "run_id": run_id,
        "ts_utc": ts_utc,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}",
        "encoding": "png",
        "content_type": "image/png",
        "content_size": int(len(png_bytes)),
        "pixel_hash": pixel_hash,
        "pixel_hash_algo": "sha256_png",
        "pixel_size": pixel_size,
        "lossless": True,
        "backend": backend,
        "monitor_index": int(monitor_index),
        "dedupe": dict(dedupe_payload),
        "content_hash": content_hash,
        "policy_snapshot_hash": event_builder.policy_snapshot_hash(),
        "encode_ms": int(encode_ms),
        "write_ms": int(write_ms),
        "render_cursor": bool(job.get("render_cursor", False)),
    }
    if cursor_payload:
        payload["cursor"] = cursor_payload
    if monitor_layout:
        payload["monitor_layout"] = monitor_layout
        for entry in monitor_layout:
            if int(entry.get("index", -1)) == int(monitor_index):
                payload["monitor"] = entry
                break
    if window_ref:
        payload["window_ref"] = window_ref
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
    if hasattr(event_builder, "capture_commit"):
        try:
            event_builder.capture_commit(
                record_id,
                "evidence.capture.frame",
                ts_utc=ts_utc,
                payload={
                    "content_hash": content_hash,
                    "payload_hash": payload.get("payload_hash"),
                    "content_size": int(len(png_bytes)),
                },
            )
        except Exception:
            pass
    telemetry = {
        "ts_utc": ts_utc,
        "record_id": record_id,
        "record_type": "evidence.capture.frame",
        "output_bytes": int(len(png_bytes)),
        "stored": True,
        "encode_ms": int(encode_ms),
        "write_ms": int(write_ms),
        "backend": backend,
    }
    record_telemetry("capture.screenshot.store", telemetry)
    record_telemetry("capture.screenshot", telemetry)
    record_telemetry(f"plugin.{str(job.get('plugin_id') or '')}".strip(".") or "plugin.builtin.capture.screenshot.windows", telemetry)
    try:
        logger.log("capture.screenshot.store", telemetry)
    except Exception:
        pass


def _store_job_overflow(
    job: dict[str, Any],
    *,
    overflow: OverflowSpool,
    storage_media: Any,
    storage_meta: Any,
    event_builder: Any,
    logger: Any,
    primary_hard_halt: bool,
) -> bool:
    """Store a screenshot job; spool to overflow on OSError / hard disk pressure.

    Returns True only when the artifact is committed into canonical stores.
    """
    record_id = str(job.get("record_id") or "")
    ts_utc = str(job.get("ts_utc") or "")
    try:
        png_bytes, payload, encode_ms, write_ms = _encode_and_build(job, event_builder=event_builder)
    except Exception:
        return False

    # If primary disk is hard-halt, go straight to overflow spool.
    if primary_hard_halt and overflow.enabled:
        try:
            overflow.write_item(record_id=record_id, payload=payload, blob=png_bytes)
            record_telemetry("capture.screenshot.overflow_write", {"ts_utc": ts_utc, "record_id": record_id})
        except Exception:
            return False
        return False

    # Try committing to canonical store first.
    try:
        _commit_payload(
            record_id,
            payload,
            png_bytes,
            storage_media=storage_media,
            storage_meta=storage_meta,
            event_builder=event_builder,
            logger=logger,
            encode_ms=encode_ms,
            write_ms=write_ms,
        )
        return True
    except FileExistsError:
        return True
    except OSError:
        # If overflow is configured, spool and continue capturing.
        if overflow.enabled:
            try:
                overflow.write_item(record_id=record_id, payload=payload, blob=png_bytes)
                record_telemetry("capture.screenshot.overflow_write", {"ts_utc": ts_utc, "record_id": record_id})
            except Exception:
                return False
        return False
    except Exception:
        return False


def _encode_and_build(job: dict[str, Any], *, event_builder: Any) -> tuple[bytes, dict[str, Any], int, int]:
    record_id = str(job.get("record_id") or "")
    run_id = str(job.get("run_id") or "")
    ts_utc = str(job.get("ts_utc") or "")
    monitor_index = int(job.get("monitor_index") or 0)
    backend = str(job.get("backend") or "mss")
    img = job.get("img")
    png_level = int(job.get("png_level") or 3)
    cursor_payload = job.get("cursor_payload")
    monitor_layout = job.get("monitor_layout")
    window_ref = job.get("window_ref")
    input_ref = job.get("input_ref")
    dedupe_payload = job.get("dedupe") if isinstance(job.get("dedupe"), dict) else {}
    media_fsync_policy = job.get("media_fsync_policy")

    encode_start = time.perf_counter()
    png_bytes = encode_png(img, compress_level=png_level)
    encode_ms = int(max(0.0, (time.perf_counter() - encode_start) * 1000.0))

    # Avoid hashing full raw pixel buffers (large + extra copies). For reliability and
    # performance, treat the PNG as the canonical stored representation.
    content_hash = hashlib.sha256(png_bytes).hexdigest()
    pixel_hash = content_hash
    width = int(getattr(img, "width", 0) or 0)
    height = int(getattr(img, "height", 0) or 0)
    pixel_size = int(width * height * 3) if width > 0 and height > 0 else 0
    payload = {
        "record_type": "evidence.capture.frame",
        "run_id": run_id,
        "ts_utc": ts_utc,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}",
        "encoding": "png",
        "content_type": "image/png",
        "content_size": int(len(png_bytes)),
        "pixel_hash": pixel_hash,
        "pixel_hash_algo": "sha256_png",
        "pixel_size": pixel_size,
        "lossless": True,
        "backend": backend,
        "monitor_index": int(monitor_index),
        "dedupe": dict(dedupe_payload),
        "content_hash": content_hash,
        "policy_snapshot_hash": event_builder.policy_snapshot_hash(),
        "encode_ms": int(encode_ms),
        "write_ms": 0,
        "render_cursor": bool(job.get("render_cursor", False)),
        "media_fsync_policy": media_fsync_policy,
    }
    if cursor_payload:
        payload["cursor"] = cursor_payload
    if monitor_layout:
        payload["monitor_layout"] = monitor_layout
        for entry in monitor_layout:
            if int(entry.get("index", -1)) == int(monitor_index):
                payload["monitor"] = entry
                break
    if window_ref:
        payload["window_ref"] = window_ref
    if input_ref:
        payload["input_ref"] = input_ref
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    return png_bytes, payload, int(encode_ms), 0


def _commit_payload(
    record_id: str,
    payload: dict[str, Any],
    png_bytes: bytes,
    *,
    storage_media: Any,
    storage_meta: Any,
    event_builder: Any,
    logger: Any,
    encode_ms: int,
    write_ms: int,
) -> None:
    ts_utc = str(payload.get("ts_utc") or "")
    media_fsync_policy = payload.get("media_fsync_policy")

    write_start = time.perf_counter()
    if hasattr(storage_media, "put_new"):
        storage_media.put_new(record_id, png_bytes, ts_utc=ts_utc, fsync_policy=media_fsync_policy)
    else:
        storage_media.put(record_id, png_bytes, ts_utc=ts_utc, fsync_policy=media_fsync_policy)
    write_ms = int(max(0.0, (time.perf_counter() - write_start) * 1000.0))
    payload["write_ms"] = int(write_ms)
    payload["encode_ms"] = int(encode_ms)
    payload["content_size"] = int(len(png_bytes))

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
    if hasattr(event_builder, "capture_commit"):
        try:
            event_builder.capture_commit(
                record_id,
                "evidence.capture.frame",
                ts_utc=ts_utc,
                payload={
                    "content_hash": payload.get("content_hash"),
                    "payload_hash": payload.get("payload_hash"),
                    "content_size": int(len(png_bytes)),
                },
            )
        except Exception:
            pass
    telemetry = {
        "ts_utc": ts_utc,
        "record_id": record_id,
        "record_type": "evidence.capture.frame",
        "output_bytes": int(len(png_bytes)),
        "stored": True,
        "encode_ms": int(encode_ms),
        "write_ms": int(write_ms),
        "backend": str(payload.get("backend") or ""),
    }
    record_telemetry("capture.screenshot.store", telemetry)
    record_telemetry("capture.screenshot", telemetry)
    try:
        logger.log("capture.screenshot.store", telemetry)
    except Exception:
        pass


def _drain_overflow_item(
    meta: dict[str, Any],
    blob: bytes,
    *,
    storage_media: Any,
    storage_meta: Any,
    event_builder: Any,
    logger: Any,
) -> bool:
    record_id = str(meta.get("record_id") or "")
    payload = meta.get("payload")
    if not record_id or not isinstance(payload, dict):
        return False
    try:
        _commit_payload(
            record_id,
            payload,
            blob,
            storage_media=storage_media,
            storage_meta=storage_meta,
            event_builder=event_builder,
            logger=logger,
            encode_ms=int(payload.get("encode_ms", 0) or 0),
            write_ms=int(payload.get("write_ms", 0) or 0),
        )
        return True
    except FileExistsError:
        return True
    except Exception:
        return False


def create_plugin(plugin_id: str, context: PluginContext) -> ScreenshotCaptureWindows:
    return ScreenshotCaptureWindows(plugin_id, context)
