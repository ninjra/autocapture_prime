"""Capture pipeline with bounded queues and segmented container output."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from autocapture_nx.capture.avi import AviMjpegWriter
from autocapture_nx.capture.queues import BoundedQueue
from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import encode_record_id_component, prefixed_id
from autocapture_nx.windows.win_capture import Frame, iter_screenshots, list_monitors

STOP_SENTINEL = object()


@dataclass
class SegmentArtifact:
    segment_id: str
    path: str
    frame_count: int
    width: int
    height: int
    ts_start_utc: str
    ts_end_utc: str
    duration_ms: int
    fps_target: int
    bitrate_kbps: int
    encoder: str
    container_type: str
    container_ext: str
    encode_ms_total: int
    encode_ms_max: int
    dropped_frames: int = 0
    queue_depth_max: int = 0
    duplicate_frames: int = 0
    duplicate_dropped: int = 0
    container_index: list[dict[str, int]] | None = None
    container_header: dict[str, int] | None = None


class DiskPressure:
    def __init__(self, warn_gb: int, soft_gb: int, critical_gb: int) -> None:
        self.warn_gb = int(warn_gb)
        self.soft_gb = int(soft_gb)
        self.critical_gb = int(critical_gb)
        self.level = "ok"

    def evaluate(self, free_gb: int) -> tuple[str, bool]:
        if free_gb <= self.critical_gb:
            new_level = "critical"
        elif free_gb <= self.soft_gb:
            new_level = "soft"
        elif free_gb <= self.warn_gb:
            new_level = "warn"
        else:
            new_level = "ok"
        changed = new_level != self.level
        self.level = new_level
        return new_level, changed


@dataclass
class DedupeDecision:
    duplicate: bool
    fingerprint: str
    repeat_count: int
    window_ms: int


class FrameDeduper:
    def __init__(self, config: dict[str, Any] | None) -> None:
        cfg = config if isinstance(config, dict) else {}
        self.enabled = bool(cfg.get("enabled", False))
        self.mode = str(cfg.get("mode", "mark_only") or "mark_only")
        self.hash_algo = str(cfg.get("hash", "blake2b") or "blake2b")
        self.sample_bytes = max(0, int(cfg.get("sample_bytes", 0) or 0))
        self.min_repeat = max(1, int(cfg.get("min_repeat", 1) or 1))
        self.window_ms = max(0, int(cfg.get("window_ms", 1500) or 0))
        self._last_hash: str | None = None
        self._last_ts: float | None = None
        self._repeat = 0

    def check(self, frame: Frame) -> DedupeDecision:
        if not self.enabled:
            return DedupeDecision(False, "", 0, self.window_ms)
        fingerprint = _hash_frame(frame.data, algo=self.hash_algo, sample_bytes=self.sample_bytes)
        now = _frame_monotonic(frame)
        duplicate = False
        if self._last_hash == fingerprint and self._last_ts is not None:
            delta_ms = int(max(0.0, (now - self._last_ts) * 1000.0))
            if self.window_ms <= 0 or delta_ms <= self.window_ms:
                self._repeat += 1
                if self._repeat >= self.min_repeat:
                    duplicate = True
            else:
                self._repeat = 0
        else:
            self._repeat = 0
        self._last_hash = fingerprint
        self._last_ts = now
        return DedupeDecision(duplicate, fingerprint, self._repeat, self.window_ms)


class ZipFrameWriter:
    def __init__(self, path: str) -> None:
        import zipfile

        self._zip = zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED)
        self._frame_count = 0

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def add_frame(self, jpeg_bytes: bytes) -> None:
        name = f"frame_{self._frame_count}.jpg"
        self._zip.writestr(name, jpeg_bytes)
        self._frame_count += 1

    def close(self, _duration_ms: int | None = None) -> None:
        self._zip.close()


class FfmpegWriter:
    def __init__(self, path: str, fps: int, encoder: str, ffmpeg_path: str, bitrate_kbps: int) -> None:
        self._path = path
        codec = "h264_nvenc" if encoder == "nvenc" else "libx264"
        cmd = [
            ffmpeg_path,
            "-y",
            "-f",
            "mjpeg",
            "-r",
            str(max(1, int(fps))),
            "-i",
            "pipe:0",
            "-c:v",
            codec,
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            f"{max(1, int(bitrate_kbps))}k",
            path,
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if os.name == "nt":
            try:
                from autocapture_nx.windows.win_sandbox import assign_job_object

                assign_job_object(self._proc.pid)
            except Exception:
                pass
        self._frame_count = 0

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def add_frame(self, jpeg_bytes: bytes) -> None:
        if not self._proc.stdin:
            raise RuntimeError("ffmpeg stdin unavailable")
        self._proc.stdin.write(jpeg_bytes)
        self._frame_count += 1

    def close(self, _duration_ms: int | None = None) -> None:
        if self._proc.stdin:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
        try:
            self._proc.wait(timeout=20)
        except subprocess.TimeoutExpired as exc:
            self._proc.kill()
            raise RuntimeError("ffmpeg did not finish") from exc
        if self._proc.returncode != 0:
            stderr = b""
            if self._proc.stderr:
                stderr = self._proc.stderr.read() or b""
            raise RuntimeError(f"ffmpeg failed: {stderr[:200].decode(errors='ignore')}")


class SegmentWriter:
    def __init__(
        self,
        spool_dir: str,
        segment_id: str,
        fps_target: int,
        bitrate_kbps: int,
        container_type: str,
        encoder: str,
        ffmpeg_path: str | None,
        fsync_policy: str = "none",
    ) -> None:
        self.segment_id = segment_id
        self._spool_dir = spool_dir
        self._fps_target = int(fps_target)
        self._bitrate_kbps = int(bitrate_kbps)
        self._container_type = container_type
        self._encoder = encoder
        self._ffmpeg_path = ffmpeg_path
        self._writer: AviMjpegWriter | ZipFrameWriter | FfmpegWriter | None = None
        self._width = 0
        self._height = 0
        self._frame_count = 0
        self._ts_start_utc: str | None = None
        self._ts_end_utc: str | None = None
        self._mono_start: float | None = None
        self._mono_end: float | None = None
        self._encode_ms_total = 0
        self._encode_ms_max = 0
        self._fsync_policy = fsync_policy
        self._final_path = self._segment_path(final=True)
        self._tmp_path = self._segment_path(final=False)

    @property
    def frame_count(self) -> int:
        return int(self._frame_count)

    def matches_frame(self, frame: Frame) -> bool:
        if self._frame_count == 0:
            return True
        return int(frame.width) == int(self._width) and int(frame.height) == int(self._height)

    def _segment_path(self, *, final: bool) -> str:
        safe = encode_record_id_component(self.segment_id)
        ext = self.container_ext()
        suffix = f".{ext}"
        if not final:
            suffix += ".tmp"
        return os.path.join(self._spool_dir, f"{safe}{suffix}")

    def container_ext(self) -> str:
        if self._container_type == "avi_mjpeg":
            return "avi"
        if self._container_type == "zip":
            return "zip"
        if self._container_type == "ffmpeg_mp4":
            return "mp4"
        return "bin"

    def add_frame(self, frame: Frame) -> None:
        if self._writer is None:
            self._width = int(frame.width)
            self._height = int(frame.height)
            os.makedirs(self._spool_dir, exist_ok=True)
            if self._container_type == "avi_mjpeg":
                self._writer = AviMjpegWriter(self._tmp_path, self._width, self._height, self._fps_target)
            elif self._container_type == "zip":
                self._writer = ZipFrameWriter(self._tmp_path)
            elif self._container_type == "ffmpeg_mp4":
                if not self._ffmpeg_path:
                    raise RuntimeError("ffmpeg path required for ffmpeg_mp4 container")
                self._writer = FfmpegWriter(
                    self._tmp_path,
                    self._fps_target,
                    self._encoder,
                    self._ffmpeg_path,
                    self._bitrate_kbps,
                )
            else:
                raise RuntimeError(f"Unsupported container: {self._container_type}")
            self._ts_start_utc = frame.ts_utc
            self._mono_start = frame.ts_monotonic
        encode_start = time.monotonic()
        assert self._writer is not None
        self._writer.add_frame(frame.data)
        encode_elapsed = int(max(0.0, (time.monotonic() - encode_start) * 1000))
        self._encode_ms_total += encode_elapsed
        self._encode_ms_max = max(self._encode_ms_max, encode_elapsed)
        self._frame_count = self._writer.frame_count
        self._ts_end_utc = frame.ts_utc
        self._mono_end = frame.ts_monotonic

    def finalize(self) -> SegmentArtifact | None:
        if self._writer is None or self._frame_count == 0:
            return None
        duration_ms, end_ts = _derive_segment_end(
            self._ts_start_utc,
            self._ts_end_utc,
            self._mono_start,
            self._mono_end,
        )
        assert self._writer is not None
        container_index = None
        container_header = None
        if isinstance(self._writer, AviMjpegWriter):
            try:
                container_index = self._writer.index_entries()
                container_header = self._writer.header_info()
            except Exception:
                container_index = None
                container_header = None
        self._writer.close(duration_ms)
        if self._fsync_policy in ("bulk", "critical"):
            _fsync_file(self._tmp_path)
        os.replace(self._tmp_path, self._final_path)
        if self._fsync_policy == "critical":
            _fsync_dir(self._spool_dir)
        return SegmentArtifact(
            segment_id=self.segment_id,
            path=self._final_path,
            frame_count=self._frame_count,
            width=self._width,
            height=self._height,
            ts_start_utc=self._ts_start_utc or _iso_utc(),
            ts_end_utc=end_ts,
            duration_ms=duration_ms,
            fps_target=self._fps_target,
            bitrate_kbps=self._bitrate_kbps,
            encoder=self._encoder,
            container_type=self._container_type,
            container_ext=self.container_ext(),
            encode_ms_total=self._encode_ms_total,
            encode_ms_max=self._encode_ms_max,
            container_index=container_index,
            container_header=container_header,
        )


class CapturePipeline:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        storage_media: Any,
        storage_meta: Any,
        event_builder: Any,
        backpressure: Any,
        logger: Any,
        window_tracker: Any | None,
        input_tracker: Any | None,
        stop_event: threading.Event | None = None,
        frame_source: Any | None = None,
    ) -> None:
        self._config = config
        self._storage_media = storage_media
        self._storage_meta = storage_meta
        self._event_builder = event_builder
        self._backpressure = backpressure
        self._logger = logger
        self._window_tracker = window_tracker
        self._input_tracker = input_tracker
        self._stop = stop_event or threading.Event()
        self._frame_source = frame_source
        self._threads: list[threading.Thread] = []
        self._frame_queue: BoundedQueue | None = None
        self._segment_queue: BoundedQueue | None = None
        self._drops_total = 0
        self._drops_segment = 0
        self._queue_depth_max = 0
        self._drops_lock = threading.Lock()
        self._segment_seq = 0
        self._backend_used = str(config.get("capture", {}).get("video", {}).get("backend", "mss"))
        backpressure_cfg = config.get("backpressure", {})
        capture_cfg = config.get("capture", {}).get("video", {})
        self._rate_lock = threading.Lock()
        self._fps_target = int(capture_cfg.get("fps_target", backpressure_cfg.get("max_fps", 30)))
        self._bitrate_kbps = int(backpressure_cfg.get("max_bitrate_kbps", 8000))
        self._jpeg_quality = int(capture_cfg.get("jpeg_quality", 90))

    def start(self) -> None:
        backpressure_cfg = self._config.get("backpressure", {})
        max_queue = int(backpressure_cfg.get("max_queue_depth", 5))
        self._frame_queue = BoundedQueue(max_queue, "drop_oldest")
        self._segment_queue = BoundedQueue(3, "block")

        grab_thread = threading.Thread(target=self._grab_loop, daemon=True)
        encode_thread = threading.Thread(target=self._encode_loop, daemon=True)
        write_thread = threading.Thread(target=self._write_loop, daemon=True)
        self._threads = [grab_thread, encode_thread, write_thread]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._frame_queue is not None:
            self._frame_queue.put(STOP_SENTINEL)
        if self._segment_queue is not None:
            self._segment_queue.put(STOP_SENTINEL)
        for thread in self._threads:
            thread.join(timeout=5)

    def join(self) -> None:
        for thread in self._threads:
            thread.join()

    def _grab_loop(self) -> None:
        capture_cfg = self._config.get("capture", {}).get("video", {})
        backpressure_cfg = self._config.get("backpressure", {})
        fps_target = self._fps_target
        bitrate_kbps = self._bitrate_kbps
        jpeg_quality = int(capture_cfg.get("jpeg_quality", self._jpeg_quality))
        activity_cfg = capture_cfg.get("activity", {})
        activity_enabled = bool(activity_cfg.get("enabled", False))
        activity_window_s = float(activity_cfg.get("active_window_s", 3))
        activity_check_s = float(activity_cfg.get("check_interval_s", 1))
        assume_idle = bool(activity_cfg.get("assume_idle_when_missing", False))
        preserve_quality = bool(activity_cfg.get("preserve_quality", True))
        active_fps = int(activity_cfg.get("active_fps", fps_target))
        idle_fps = int(activity_cfg.get("idle_fps", fps_target))
        active_bitrate = int(activity_cfg.get("active_bitrate_kbps", bitrate_kbps))
        idle_bitrate = int(activity_cfg.get("idle_bitrate_kbps", bitrate_kbps))
        active_quality = int(activity_cfg.get("active_jpeg_quality", jpeg_quality))
        idle_quality = int(activity_cfg.get("idle_jpeg_quality", jpeg_quality))
        base_fps = int(fps_target)
        base_bitrate = int(bitrate_kbps)
        base_quality = int(jpeg_quality)
        if preserve_quality:
            active_bitrate = int(base_bitrate)
            idle_bitrate = int(base_bitrate)
            active_quality = int(base_quality)
            idle_quality = int(base_quality)
        activity_mode: str | None = None
        last_activity_check = 0.0
        backend = str(capture_cfg.get("backend", "mss"))
        disk_cfg = self._config.get("storage", {}).get("disk_pressure", {})
        warn_free = int(disk_cfg.get("warn_free_gb", 200))
        soft_free = int(disk_cfg.get("soft_free_gb", warn_free))
        critical_free = int(disk_cfg.get("critical_free_gb", 50))
        disk_pressure = DiskPressure(warn_free, soft_free, critical_free)
        disk_interval_s = float(disk_cfg.get("interval_s", 1.0) or 1.0)
        if disk_interval_s <= 0:
            disk_interval_s = 1.0
        disk_interval_s = min(max(1.0, disk_interval_s), 60.0)
        last_disk_check = 0.0
        degraded = False

        frame_queue = self._frame_queue
        if frame_queue is None:
            return

        def fps_provider() -> int:
            return max(1, int(fps_target))

        def jpeg_quality_provider() -> int:
            with self._rate_lock:
                return int(self._jpeg_quality)

        monitor_index = int(capture_cfg.get("monitor_index", 0))
        resolution = capture_cfg.get("resolution", "native")

        def _apply_disk_degrade(base_fps_val: int, base_bitrate_val: int, base_quality_val: int) -> tuple[int, int, int]:
            min_fps = int(backpressure_cfg.get("min_fps", 5))
            min_bitrate = int(backpressure_cfg.get("min_bitrate_kbps", 1000))
            degraded_fps = max(min_fps, max(1, int(base_fps_val) // 2))
            if preserve_quality:
                degraded_bitrate = int(base_bitrate_val)
                degraded_quality = int(base_quality_val)
            else:
                degraded_bitrate = max(min_bitrate, max(1, int(base_bitrate_val) // 2))
                degraded_quality = max(10, int(int(base_quality_val) * 0.7))
            return degraded_fps, degraded_bitrate, degraded_quality

        def _activity_snapshot() -> tuple[str, float, float]:
            idle_seconds = 0.0
            activity_score = 0.0
            if self._input_tracker is not None and hasattr(self._input_tracker, "activity_signal"):
                try:
                    signal = self._input_tracker.activity_signal()
                except Exception:
                    signal = {}
                if isinstance(signal, dict):
                    idle_seconds = float(signal.get("idle_seconds", 0.0))
                    activity_score = float(signal.get("activity_score", 0.0) or 0.0)
                    user_active = bool(signal.get("user_active", idle_seconds < activity_window_s)) or activity_score >= 0.5
                    return ("active" if user_active else "idle", idle_seconds, activity_score)
            if self._input_tracker is not None and hasattr(self._input_tracker, "idle_seconds"):
                try:
                    idle_seconds = float(self._input_tracker.idle_seconds())
                except Exception:
                    idle_seconds = 0.0
                user_active = idle_seconds < activity_window_s
                return ("active" if user_active else "idle", idle_seconds, activity_score)
            idle_seconds = float("inf") if assume_idle else 0.0
            return ("idle" if idle_seconds >= activity_window_s else "active", idle_seconds, activity_score)
        backend_used, frame_iter = _frame_iter(
            backend,
            fps_provider,
            frame_source=self._frame_source,
            jpeg_quality=jpeg_quality_provider if activity_enabled else int(jpeg_quality),
            monitor_index=monitor_index,
            resolution=resolution,
        )
        self._backend_used = backend_used
        if backend_used != backend:
            backend_payload: dict[str, Any] = {"requested": backend, "used": backend_used}
            self._event_builder.journal_event("capture.backend_fallback", backend_payload)
            self._event_builder.ledger_entry(
                "capture.backend_fallback",
                inputs=[],
                outputs=[],
                payload={"event": "capture.backend_fallback", **backend_payload},
            )

        for frame in frame_iter:
            if self._stop.is_set():
                break
            now = time.monotonic()
            if activity_enabled and (now - last_activity_check) >= max(0.2, activity_check_s):
                mode, idle_seconds, activity_score = _activity_snapshot()
                if mode != activity_mode:
                    activity_mode = mode
                    if mode == "active":
                        base_fps = int(active_fps)
                        base_bitrate = int(active_bitrate)
                        base_quality = int(active_quality)
                    else:
                        base_fps = int(idle_fps)
                        base_bitrate = int(idle_bitrate)
                        base_quality = int(idle_quality)
                    if degraded:
                        fps_target, bitrate_kbps, quality = _apply_disk_degrade(base_fps, base_bitrate, base_quality)
                    else:
                        fps_target = int(base_fps)
                        bitrate_kbps = int(base_bitrate)
                        quality = int(base_quality)
                    with self._rate_lock:
                        self._fps_target = fps_target
                        self._bitrate_kbps = bitrate_kbps
                        self._jpeg_quality = int(quality)
                    activity_payload: dict[str, Any] = {
                        "mode": mode,
                        "idle_seconds": float(idle_seconds),
                        "activity_score": float(activity_score),
                        "fps_target": int(fps_target),
                        "bitrate_kbps": int(bitrate_kbps),
                        "jpeg_quality": int(quality),
                        "disk_degraded": bool(degraded),
                        "preserve_quality": bool(preserve_quality),
                    }
                    self._logger.log("capture.activity", activity_payload)
                    self._event_builder.journal_event("capture.activity", activity_payload)
                    self._event_builder.ledger_entry(
                        "capture.activity",
                        inputs=[],
                        outputs=[],
                        payload={"event": "capture.activity", **activity_payload},
                    )
                last_activity_check = now
            before_drops = frame_queue.stats.dropped
            ok = frame_queue.put(frame)
            after_drops = frame_queue.stats.dropped
            if not ok or after_drops > before_drops:
                dropped = after_drops - before_drops
                if dropped <= 0:
                    dropped = 1
                with self._drops_lock:
                    self._drops_total += dropped
                    self._drops_segment += dropped
                drop_payload: dict[str, Any] = {
                    "dropped_frames": int(dropped),
                    "queue_depth": int(frame_queue.qsize()),
                    "policy": "drop_oldest",
                }
                self._event_builder.journal_event("capture.drop", drop_payload)
                self._event_builder.ledger_entry(
                    "capture.drop",
                    inputs=[],
                    outputs=[],
                    payload={"event": "capture.drop", **drop_payload},
                )

            with self._drops_lock:
                self._queue_depth_max = max(self._queue_depth_max, frame_queue.qsize())

            if now - last_disk_check >= disk_interval_s:
                free_gb = _free_gb(self._config.get("storage", {}).get("data_dir", "."))
                level, changed = disk_pressure.evaluate(free_gb)
                if changed:
                    pressure_payload: dict[str, Any] = {
                        "level": level,
                        "free_gb": int(free_gb),
                        "warn_gb": int(warn_free),
                        "soft_gb": int(soft_free),
                        "critical_gb": int(critical_free),
                    }
                    self._event_builder.journal_event("disk.pressure", pressure_payload)
                    self._event_builder.ledger_entry(
                        "disk.pressure",
                        inputs=[],
                        outputs=[],
                        payload={"event": "disk.pressure", **pressure_payload},
                    )
                if level == "soft" and not degraded:
                    degraded = True
                    fps_target, bitrate_kbps, quality = _apply_disk_degrade(base_fps, base_bitrate, base_quality)
                    with self._rate_lock:
                        self._fps_target = fps_target
                        self._bitrate_kbps = bitrate_kbps
                        self._jpeg_quality = int(quality)
                    degrade_payload: dict[str, Any] = {
                        "fps_target": int(fps_target),
                        "bitrate_kbps": int(bitrate_kbps),
                        "jpeg_quality": int(quality),
                        "level": level,
                    }
                    self._event_builder.journal_event("capture.degrade", degrade_payload)
                    self._event_builder.ledger_entry(
                        "capture.degrade",
                        inputs=[],
                        outputs=[],
                        payload={"event": "capture.degrade", **degrade_payload},
                    )
                elif level == "critical":
                    critical_payload: dict[str, Any] = {
                        "free_gb": int(free_gb),
                        "threshold_gb": int(critical_free),
                    }
                    self._event_builder.journal_event("disk.critical", critical_payload)
                    self._event_builder.ledger_entry(
                        "disk.critical",
                        inputs=[],
                        outputs=[],
                        payload={"event": "disk.critical", **critical_payload},
                    )
                    self._stop.set()
                    break
                elif level == "ok" and degraded:
                    degraded = False
                    fps_target = int(base_fps)
                    bitrate_kbps = int(base_bitrate)
                    quality = int(base_quality)
                    with self._rate_lock:
                        self._fps_target = fps_target
                        self._bitrate_kbps = bitrate_kbps
                        self._jpeg_quality = int(quality)
                    restore_payload: dict[str, Any] = {
                        "fps_target": int(fps_target),
                        "bitrate_kbps": int(bitrate_kbps),
                        "jpeg_quality": int(quality),
                        "level": level,
                    }
                    self._event_builder.journal_event("capture.restore", restore_payload)
                    self._event_builder.ledger_entry(
                        "capture.restore",
                        inputs=[],
                        outputs=[],
                        payload={"event": "capture.restore", **restore_payload},
                    )
                last_disk_check = now

            queue_depth = frame_queue.qsize()
            update = self._backpressure.adjust(
                {"queue_depth": int(queue_depth), "now": now},
                {"fps_target": fps_target, "bitrate_kbps": bitrate_kbps},
            )
            updated_fps = int(update.get("fps_target", fps_target))
            updated_bitrate = int(update.get("bitrate_kbps", bitrate_kbps))
            if activity_enabled:
                updated_fps = min(updated_fps, int(base_fps))
                updated_bitrate = min(updated_bitrate, int(base_bitrate))
            if degraded:
                degraded_fps, degraded_bitrate, _quality = _apply_disk_degrade(base_fps, base_bitrate, base_quality)
                updated_fps = min(updated_fps, int(degraded_fps))
                updated_bitrate = min(updated_bitrate, int(degraded_bitrate))
            if preserve_quality:
                updated_bitrate = int(base_bitrate)
            if updated_fps != fps_target or updated_bitrate != bitrate_kbps:
                self._logger.log(
                    "capture.rate_change",
                    {
                        "fps_prev": int(fps_target),
                        "fps_target": int(updated_fps),
                        "bitrate_prev_kbps": int(bitrate_kbps),
                        "bitrate_target_kbps": int(updated_bitrate),
                        "queue_depth": int(queue_depth),
                    },
                )
                fps_target = updated_fps
                bitrate_kbps = updated_bitrate
                with self._rate_lock:
                    self._fps_target = fps_target
                    self._bitrate_kbps = bitrate_kbps

        # Signal end of stream
        frame_queue.put(STOP_SENTINEL)

    def _encode_loop(self) -> None:
        capture_cfg = self._config.get("capture", {}).get("video", {})
        segment_seconds = int(capture_cfg.get("segment_seconds", 60))
        container_type = str(capture_cfg.get("container", "avi_mjpeg"))
        encoder = str(capture_cfg.get("encoder", "cpu"))
        ffmpeg_path_cfg = str(capture_cfg.get("ffmpeg_path", "")).strip()
        resolved_container, ffmpeg_path = _resolve_container(container_type, ffmpeg_path_cfg)
        if resolved_container != container_type:
            container_payload: dict[str, Any] = {"requested": container_type, "used": resolved_container}
            self._event_builder.journal_event("capture.container_fallback", container_payload)
            self._event_builder.ledger_entry(
                "capture.container_fallback",
                inputs=[],
                outputs=[],
                payload={"event": "capture.container_fallback", **container_payload},
            )
        container_type = resolved_container
        with self._rate_lock:
            fps_target = self._fps_target
            bitrate_kbps = self._bitrate_kbps
        spool_dir = self._config.get("storage", {}).get("spool_dir", "data/spool")
        storage_cfg = self._config.get("storage", {})
        fsync_policy = str(storage_cfg.get("fsync_policy", "none") or "none")
        run_id = self._config.get("runtime", {}).get("run_id", "run")
        backend = self._backend_used
        deduper = FrameDeduper(capture_cfg.get("dedupe", {}))

        frame_queue = self._frame_queue
        segment_queue = self._segment_queue
        if frame_queue is None or segment_queue is None:
            return

        segment: SegmentWriter | None = None
        segment_start_mono: float | None = None
        segment_dup_frames = 0
        segment_dup_dropped = 0
        while True:
            frame = frame_queue.get(timeout=0.2)
            if frame is None:
                if self._stop.is_set():
                    continue
                continue
            if frame is STOP_SENTINEL:
                if segment is not None:
                    artifact = segment.finalize()
                    if artifact:
                        dropped_frames, depth_max = self._pop_drop_stats()
                        artifact.dropped_frames = dropped_frames
                        artifact.queue_depth_max = depth_max
                        artifact.duplicate_frames = int(segment_dup_frames)
                        artifact.duplicate_dropped = int(segment_dup_dropped)
                        segment_queue.put((artifact, backend))
                    segment = None
                segment_queue.put(STOP_SENTINEL)
                break
            if self._stop.is_set():
                continue
            if segment is not None and not segment.matches_frame(frame):
                artifact = segment.finalize()
                if artifact:
                    dropped_frames, depth_max = self._pop_drop_stats()
                    artifact.dropped_frames = dropped_frames
                    artifact.queue_depth_max = depth_max
                    artifact.duplicate_frames = int(segment_dup_frames)
                    artifact.duplicate_dropped = int(segment_dup_dropped)
                    segment_queue.put((artifact, backend))
                segment = None
                segment_start_mono = None
                segment_dup_frames = 0
                segment_dup_dropped = 0
            if segment is None:
                with self._rate_lock:
                    fps_target = self._fps_target
                    bitrate_kbps = self._bitrate_kbps
                segment_id = prefixed_id(run_id, "segment", self._segment_seq)
                self._segment_seq += 1
                segment = SegmentWriter(
                    spool_dir,
                    segment_id,
                    fps_target=fps_target,
                    bitrate_kbps=bitrate_kbps,
                    container_type=container_type,
                    encoder=encoder,
                    ffmpeg_path=ffmpeg_path,
                    fsync_policy=fsync_policy,
                )
                segment_start_mono = _frame_monotonic(frame)
                segment_dup_frames = 0
                segment_dup_dropped = 0
            dedupe_decision = deduper.check(frame)
            if dedupe_decision.duplicate:
                segment_dup_frames += 1
                if deduper.mode == "drop" and segment.frame_count > 0:
                    segment_dup_dropped += 1
                    continue
            segment.add_frame(frame)
            if segment_start_mono is None:
                segment_start_mono = _frame_monotonic(frame)
            now_mono = _frame_monotonic(frame)
            if now_mono - segment_start_mono >= segment_seconds:
                artifact = segment.finalize()
                if artifact:
                    dropped_frames, depth_max = self._pop_drop_stats()
                    artifact.dropped_frames = dropped_frames
                    artifact.queue_depth_max = depth_max
                    artifact.duplicate_frames = int(segment_dup_frames)
                    artifact.duplicate_dropped = int(segment_dup_dropped)
                    segment_queue.put((artifact, backend))
                segment = None
                segment_start_mono = None
                segment_dup_frames = 0
                segment_dup_dropped = 0

    def _write_loop(self) -> None:
        segment_queue = self._segment_queue
        if segment_queue is None:
            return
        while True:
            item = segment_queue.get(timeout=0.5)
            if item is None:
                if self._stop.is_set():
                    break
                continue
            if item is STOP_SENTINEL:
                break
            artifact, backend = item
            if artifact is None:
                continue
            self._write_segment(artifact, backend)

    def _write_segment(self, artifact: SegmentArtifact, backend: str) -> None:
        window_ref = _snapshot_window(self._window_tracker)
        input_ref = _snapshot_input(self._input_tracker)
        policy_hash = self._event_builder.policy_snapshot_hash()
        capture_cfg = self._config.get("capture", {}).get("video", {})
        monitor_index = int(capture_cfg.get("monitor_index", 0))
        jpeg_quality = int(capture_cfg.get("jpeg_quality", 90))
        segment_seconds = int(capture_cfg.get("segment_seconds", 60))
        dedupe_cfg = capture_cfg.get("dedupe", {})
        dedupe_enabled = bool(dedupe_cfg.get("enabled", False)) if isinstance(dedupe_cfg, dict) else False
        dedupe_mode = str(dedupe_cfg.get("mode", "mark_only") or "mark_only") if isinstance(dedupe_cfg, dict) else "mark_only"
        dedupe_hash = str(dedupe_cfg.get("hash", "blake2b") or "blake2b") if isinstance(dedupe_cfg, dict) else "blake2b"
        dedupe_window_ms = int(dedupe_cfg.get("window_ms", 1500) or 0) if isinstance(dedupe_cfg, dict) else 1500
        dedupe_min_repeat = int(dedupe_cfg.get("min_repeat", 1) or 1) if isinstance(dedupe_cfg, dict) else 1
        dedupe_sample_bytes = int(dedupe_cfg.get("sample_bytes", 0) or 0) if isinstance(dedupe_cfg, dict) else 0
        fps_effective = _safe_div(artifact.frame_count * 1000, artifact.duration_ms or 1)
        run_id = str(self._config.get("runtime", {}).get("run_id", ""))
        metadata = {
            "record_type": "evidence.capture.segment",
            "run_id": run_id,
            "segment_id": artifact.segment_id,
            "ts_start_utc": artifact.ts_start_utc,
            "ts_end_utc": artifact.ts_end_utc,
            "duration_ms": int(artifact.duration_ms),
            "frame_count": int(artifact.frame_count),
            "width": int(artifact.width),
            "height": int(artifact.height),
            "resolution": f"{int(artifact.width)}x{int(artifact.height)}",
            "backend": backend,
            "container": {
                "type": artifact.container_type,
                "ext": artifact.container_ext,
                "version": 1,
            },
            "fps_target": int(artifact.fps_target),
            "fps_effective": int(fps_effective),
            "bitrate_kbps": int(artifact.bitrate_kbps),
            "encoder": artifact.encoder,
            "jpeg_quality": int(jpeg_quality),
            "monitor_index": int(monitor_index),
            "segment_seconds": int(segment_seconds),
            "drops": {
                "frames": int(artifact.dropped_frames),
                "queue_depth_max": int(artifact.queue_depth_max),
                "policy": "drop_oldest",
            },
            "dedupe": {
                "enabled": bool(dedupe_enabled),
                "mode": dedupe_mode,
                "hash": dedupe_hash,
                "window_ms": int(dedupe_window_ms),
                "min_repeat": int(dedupe_min_repeat),
                "sample_bytes": int(dedupe_sample_bytes),
                "duplicate_frames": int(artifact.duplicate_frames),
                "duplicate_dropped": int(artifact.duplicate_dropped),
            },
            "encode_ms_total": int(artifact.encode_ms_total),
            "encode_ms_max": int(artifact.encode_ms_max),
            "policy_snapshot_hash": policy_hash,
        }
        if artifact.container_index:
            metadata["container"]["index"] = artifact.container_index
        if artifact.container_header:
            metadata["container"]["header"] = artifact.container_header
        if window_ref:
            metadata["window_ref"] = window_ref
        if input_ref:
            metadata["input_ref"] = input_ref
        monitor_layout = _monitor_layout()
        if monitor_layout:
            metadata["monitor_layout"] = monitor_layout
            if monitor_index is not None:
                for entry in monitor_layout:
                    if int(entry.get("index", -1)) == int(monitor_index):
                        metadata["monitor"] = entry
                        break
        cursor_cfg = self._config.get("capture", {}).get("cursor", {})
        if isinstance(cursor_cfg, dict) and cursor_cfg.get("enabled", False):
            try:
                from autocapture_nx.windows.win_cursor import current_cursor

                cursor = current_cursor()
            except Exception:
                cursor = None
            if cursor is not None:
                cursor_payload = {"x": int(cursor.x), "y": int(cursor.y), "visible": bool(cursor.visible)}
                if cursor_cfg.get("include_shape", True):
                    cursor_payload["handle"] = int(cursor.handle)
                metadata["cursor"] = cursor_payload

        content_hash = None
        try:
            with open(artifact.path, "rb") as handle:
                if hasattr(self._storage_media, "put_stream"):
                    import hashlib

                    hasher = hashlib.sha256()

                    class _HashingReader:
                        def __init__(self, source):
                            self._source = source

                        def read(self, size: int = -1) -> bytes:
                            data = self._source.read(size)
                            if data:
                                hasher.update(data)
                            return data

                    reader = _HashingReader(handle)
                    self._storage_media.put_stream(artifact.segment_id, reader, ts_utc=artifact.ts_start_utc)
                    content_hash = hasher.hexdigest()
                else:
                    data = handle.read()
                    if data:
                        import hashlib

                        content_hash = hashlib.sha256(data).hexdigest()
                    if hasattr(self._storage_media, "put"):
                        self._storage_media.put(artifact.segment_id, data, ts_utc=artifact.ts_start_utc)
                    else:
                        self._storage_media.put(artifact.segment_id, data)
            if content_hash:
                metadata["content_hash"] = content_hash
            metadata["payload_hash"] = sha256_canonical({k: v for k, v in metadata.items() if k != "payload_hash"})
            if hasattr(self._storage_meta, "put_new"):
                self._storage_meta.put_new(artifact.segment_id, metadata)
            else:
                self._storage_meta.put(artifact.segment_id, metadata)
            self._event_builder.journal_event(
                "capture.segment",
                metadata,
                event_id=artifact.segment_id,
                ts_utc=artifact.ts_start_utc,
            )
            self._event_builder.ledger_entry(
                "capture",
                inputs=[],
                outputs=[artifact.segment_id],
                payload=metadata,
                entry_id=artifact.segment_id,
                ts_utc=artifact.ts_start_utc,
            )
            seal_payload = {
                "event": "segment.sealed",
                "segment_id": artifact.segment_id,
                "content_hash": content_hash,
            }
            self._event_builder.ledger_entry(
                "segment.seal",
                inputs=[artifact.segment_id],
                outputs=[],
                payload=seal_payload,
                ts_utc=artifact.ts_end_utc,
            )
        except Exception as exc:
            failure = {
                "event": "capture.partial_failure",
                "segment_id": artifact.segment_id,
                "error": str(exc),
            }
            self._event_builder.journal_event(
                "capture.partial_failure",
                failure,
                ts_utc=artifact.ts_start_utc,
            )
            self._event_builder.ledger_entry(
                "capture.partial_failure",
                inputs=[artifact.segment_id],
                outputs=[],
                payload=failure,
                ts_utc=artifact.ts_start_utc,
            )
            return
        try:
            os.remove(artifact.path)
        except FileNotFoundError:
            pass

    def _pop_drop_stats(self) -> tuple[int, int]:
        with self._drops_lock:
            dropped = self._drops_segment
            depth = self._queue_depth_max
            self._drops_segment = 0
            self._queue_depth_max = 0
        return dropped, depth


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derive_segment_end(
    start_utc: str | None,
    end_utc: str | None,
    start_mono: float | None,
    end_mono: float | None,
) -> tuple[int, str]:
    duration_ms = 0
    if start_mono is not None and end_mono is not None:
        duration_ms = int(max(0.0, (end_mono - start_mono) * 1000))
    if not start_utc:
        start_utc = end_utc or _iso_utc()
    if duration_ms > 0:
        try:
            start_dt = _parse_iso(start_utc)
            end_dt = start_dt + timedelta(milliseconds=duration_ms)
            return duration_ms, end_dt.isoformat()
        except Exception:
            return duration_ms, end_utc or start_utc
    return duration_ms, end_utc or start_utc


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _safe_div(numerator: int, denom: int) -> int:
    if denom <= 0:
        return int(numerator)
    return int(numerator // denom)


def _frame_monotonic(frame: Frame) -> float:
    if frame.ts_monotonic is not None:
        return float(frame.ts_monotonic)
    return time.monotonic()


def _free_gb(path: str) -> int:
    total, used, free = shutil.disk_usage(path)
    return int(free // (1024 ** 3))


def _fsync_file(path: str) -> None:
    try:
        with open(path, "rb") as handle:
            os.fsync(handle.fileno())
    except Exception:
        return


def _fsync_dir(path: str) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except Exception:
        return
    try:
        os.fsync(fd)
    except Exception:
        pass
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


def _hash_frame(data: bytes, *, algo: str, sample_bytes: int) -> str:
    payload = data[:sample_bytes] if sample_bytes and sample_bytes > 0 else data
    name = str(algo).lower()
    if name in {"adler32", "adler"}:
        checksum = zlib.adler32(payload)
        return f"adler32:{checksum:08x}:{len(payload)}"
    if name in {"blake2", "blake2b"}:
        return f"blake2b:{hashlib.blake2b(payload, digest_size=16).hexdigest()}"
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


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


def _create_dxcam(monitor_index: int):
    import dxcam

    candidates = [
        {"output_color": "RGB", "output_idx": int(monitor_index)},
        {"output_color": "RGB", "output_index": int(monitor_index)},
        {"output_color": "RGB", "monitor_idx": int(monitor_index)},
        {"output_color": "RGB", "monitor": int(monitor_index)},
        {"output_color": "RGB"},
    ]
    for kwargs in candidates:
        try:
            cam = dxcam.create(**kwargs)
        except TypeError:
            continue
        except Exception:
            continue
        if cam is not None:
            return cam
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


def _resolve_container(container_type: str, ffmpeg_path: str | None) -> tuple[str, str | None]:
    if container_type == "ffmpeg_mp4":
        path = ffmpeg_path or shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
        if not path:
            return "avi_mjpeg", None
        return "ffmpeg_mp4", path
    return container_type, None


def _frame_iter(
    backend: str,
    fps_provider: Callable[[], int],
    *,
    frame_source: Any | None,
    jpeg_quality: int | Callable[[], int],
    monitor_index: int,
    resolution: str | None,
) -> tuple[str, Any]:
    if backend == "auto":
        try:
            return "dxcam", _dxcam_frames(
                fps_provider,
                jpeg_quality=jpeg_quality,
                monitor_index=monitor_index,
                resolution=resolution,
            )
        except Exception:
            return "mss", iter_screenshots(
                fps_provider,
                frame_source=frame_source,
                jpeg_quality=jpeg_quality,
                monitor_index=monitor_index,
                resolution=resolution,
            )
    if backend == "dxcam":
        try:
            return "dxcam", _dxcam_frames(
                fps_provider,
                jpeg_quality=jpeg_quality,
                monitor_index=monitor_index,
                resolution=resolution,
            )
        except Exception:
            return "mss", iter_screenshots(
                fps_provider,
                frame_source=frame_source,
                jpeg_quality=jpeg_quality,
                monitor_index=monitor_index,
                resolution=resolution,
            )
    return backend, iter_screenshots(
        fps_provider,
        frame_source=frame_source,
        jpeg_quality=jpeg_quality,
        monitor_index=monitor_index,
        resolution=resolution,
    )


def _dxcam_frames(
    fps_provider: Callable[[], int],
    *,
    jpeg_quality: int | Callable[[], int],
    monitor_index: int,
    resolution: str | None,
):
    if os.name != "nt":
        raise RuntimeError("DXCAM capture supported on Windows only")
    try:
        from PIL import Image
    except Exception as exc:
        raise RuntimeError(f"Missing DXCAM dependency: {exc}")
    cam = _create_dxcam(monitor_index)
    if cam is None:
        raise RuntimeError("DXCAM not available")
    target_size = _parse_resolution(resolution)
    while True:
        frame = cam.grab()
        if frame is None:
            time.sleep(1.0 / max(1, int(fps_provider())))
            continue
        img = Image.fromarray(frame)
        if target_size and (img.width, img.height) != target_size:
            img = img.resize(target_size)
        from io import BytesIO

        bio = BytesIO()
        quality = jpeg_quality() if callable(jpeg_quality) else jpeg_quality
        img.save(bio, format="JPEG", quality=int(quality))
        data = bio.getvalue()
        yield Frame(ts_utc=_iso_utc(), data=data, width=img.width, height=img.height, ts_monotonic=time.monotonic())
