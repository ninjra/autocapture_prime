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
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from autocapture_nx.windows.win_cursor import CursorInfo, CursorShape

from autocapture_nx.capture.avi import AviMjpegWriter
from autocapture_nx.capture.queues import BoundedQueue
from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import encode_record_id_component, prefixed_id
from collections import deque

from autocapture_nx.kernel.telemetry import record_telemetry, percentile
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
    def __init__(self, warn_gb: int, soft_gb: int, critical_gb: int, *, soft_mb: int = 0, hard_mb: int = 0) -> None:
        self.warn_gb = int(warn_gb)
        self.soft_gb = int(soft_gb)
        self.critical_gb = int(critical_gb)
        self.soft_mb = int(soft_mb)
        self.hard_mb = int(hard_mb)
        self.level = "ok"

    def evaluate(self, free_gb: int, free_bytes: int | None = None) -> tuple[str, bool]:
        if free_bytes is None:
            free_bytes = int(free_gb) * (1024 ** 3)
        if self.hard_mb > 0 and free_bytes <= (self.hard_mb * 1024 * 1024):
            new_level = "critical"
        elif self.soft_mb > 0 and free_bytes <= (self.soft_mb * 1024 * 1024):
            new_level = "soft"
        elif free_gb <= self.critical_gb:
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
    def __init__(self, path: str, frame_ext: str = "jpg") -> None:
        import zipfile

        self._zip = zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED)
        self._frame_count = 0
        ext = str(frame_ext or "jpg").strip().lstrip(".")
        self._frame_ext = ext or "jpg"

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def add_frame(self, jpeg_bytes: bytes) -> None:
        name = f"frame_{self._frame_count}.{self._frame_ext}"
        self._zip.writestr(name, jpeg_bytes)
        self._frame_count += 1

    def close(self, _duration_ms: int | None = None) -> None:
        self._zip.close()


class FfmpegWriter:
    def __init__(
        self,
        path: str,
        fps: int,
        encoder: str,
        ffmpeg_path: str,
        bitrate_kbps: int,
        *,
        job_limits: dict[str, Any] | None = None,
    ) -> None:
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

                assign_job_object(self._proc.pid, limits=job_limits)
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


class FfmpegRawWriter:
    def __init__(
        self,
        path: str,
        fps: int,
        ffmpeg_path: str,
        width: int,
        height: int,
        *,
        job_limits: dict[str, Any] | None = None,
    ) -> None:
        self._path = path
        cmd = [
            ffmpeg_path,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{int(width)}x{int(height)}",
            "-r",
            str(max(1, int(fps))),
            "-i",
            "pipe:0",
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-g",
            "1",
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

                assign_job_object(self._proc.pid, limits=job_limits)
            except Exception:
                pass
        self._frame_count = 0

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def add_frame(self, rgb_bytes: bytes) -> None:
        if not self._proc.stdin:
            raise RuntimeError("ffmpeg stdin unavailable")
        self._proc.stdin.write(rgb_bytes)
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
        frame_format: str = "jpeg",
        fsync_policy: str = "none",
        job_limits: dict[str, Any] | None = None,
    ) -> None:
        self.segment_id = segment_id
        self._spool_dir = spool_dir
        self._fps_target = int(fps_target)
        self._bitrate_kbps = int(bitrate_kbps)
        self._container_type = container_type
        self._encoder = encoder
        self._ffmpeg_path = ffmpeg_path
        self._frame_format = str(frame_format or "jpeg").strip().lower()
        if self._frame_format not in {"jpeg", "png", "rgb"}:
            self._frame_format = "jpeg"
        self._job_limits = job_limits if isinstance(job_limits, dict) else None
        self._writer: AviMjpegWriter | ZipFrameWriter | FfmpegWriter | FfmpegRawWriter | None = None
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
        if self._container_type == "ffmpeg_lossless":
            return "mkv"
        return "bin"

    def add_frame(self, frame: Frame) -> None:
        if self._writer is None:
            self._width = int(frame.width)
            self._height = int(frame.height)
            os.makedirs(self._spool_dir, exist_ok=True)
            if self._container_type == "avi_mjpeg":
                if self._frame_format != "jpeg":
                    raise RuntimeError("avi_mjpeg requires jpeg frames")
                self._writer = AviMjpegWriter(self._tmp_path, self._width, self._height, self._fps_target)
            elif self._container_type == "zip":
                if self._frame_format not in {"jpeg", "png"}:
                    raise RuntimeError("zip container requires jpeg or png frames")
                frame_ext = "jpg" if self._frame_format == "jpeg" else "png"
                self._writer = ZipFrameWriter(self._tmp_path, frame_ext=frame_ext)
            elif self._container_type == "ffmpeg_mp4":
                if self._frame_format != "jpeg":
                    raise RuntimeError("ffmpeg_mp4 requires jpeg frames")
                if not self._ffmpeg_path:
                    raise RuntimeError("ffmpeg path required for ffmpeg_mp4 container")
                self._writer = FfmpegWriter(
                    self._tmp_path,
                    self._fps_target,
                    self._encoder,
                    self._ffmpeg_path,
                    self._bitrate_kbps,
                    job_limits=self._job_limits,
                )
            elif self._container_type == "ffmpeg_lossless":
                if self._frame_format != "rgb":
                    raise RuntimeError("ffmpeg_lossless requires rgb frames")
                if not self._ffmpeg_path:
                    raise RuntimeError("ffmpeg path required for ffmpeg_lossless container")
                self._writer = FfmpegRawWriter(
                    self._tmp_path,
                    self._fps_target,
                    self._ffmpeg_path,
                    self._width,
                    self._height,
                    job_limits=self._job_limits,
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
        plugin_id: str | None = None,
        storage_media: Any,
        storage_meta: Any,
        event_builder: Any,
        backpressure: Any,
        logger: Any,
        window_tracker: Any | None,
        input_tracker: Any | None,
        governor: Any | None = None,
        stop_event: threading.Event | None = None,
        frame_source: Any | None = None,
    ) -> None:
        self._config = config
        self._storage_media = storage_media
        self._storage_meta = storage_meta
        self._event_builder = event_builder
        self._backpressure = backpressure
        self._logger = logger
        self._plugin_id = str(plugin_id) if plugin_id else ""
        self._window_tracker = window_tracker
        self._input_tracker = input_tracker
        self._governor = governor
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
        self._start_mono = time.monotonic()
        self._last_output_mono: float | None = None
        self._last_output_lock = threading.Lock()
        self._last_segment_id: str | None = None
        self._queue_depth_samples: deque[int] = deque(maxlen=240)
        self._lag_samples: deque[float] = deque(maxlen=240)
        self._throttle_events = 0
        self._last_throttle_ts = 0.0
        self._last_silence_ts = 0.0
        capture_cfg = config.get("capture", {}).get("video", {})
        runtime_cfg = config.get("runtime", {}) if isinstance(config, dict) else {}
        job_limits_cfg = runtime_cfg.get("job_limits", {}) if isinstance(runtime_cfg, dict) else {}
        self._capture_job_limits = job_limits_cfg.get("capture") if isinstance(job_limits_cfg, dict) else None
        self._backend_used = str(capture_cfg.get("backend", "mss"))
        requested_container = str(capture_cfg.get("container", "avi_mjpeg") or "avi_mjpeg")
        ffmpeg_path_cfg = str(capture_cfg.get("ffmpeg_path", "") or "").strip()
        resolved_container, ffmpeg_path = _resolve_container(requested_container, ffmpeg_path_cfg)
        if resolved_container != requested_container and self._event_builder is not None:
            container_payload: dict[str, Any] = {"requested": requested_container, "used": resolved_container}
            try:
                self._event_builder.journal_event("capture.container_fallback", container_payload)
                self._event_builder.ledger_entry(
                    "capture.container_fallback",
                    inputs=[],
                    outputs=[],
                    payload={"event": "capture.container_fallback", **container_payload},
                )
            except Exception:
                pass
        self._container_type = resolved_container
        self._ffmpeg_path = ffmpeg_path
        frame_format = _resolve_frame_format(
            capture_cfg.get("frame_format", "auto"),
            requested_container,
            resolved_container,
        )
        coerced = _coerce_frame_format(frame_format, self._container_type)
        if coerced != frame_format and self._event_builder is not None:
            payload = {"requested": frame_format, "used": coerced, "container": self._container_type}
            try:
                self._event_builder.journal_event("capture.frame_format_fallback", payload)
                self._event_builder.ledger_entry(
                    "capture.frame_format_fallback",
                    inputs=[],
                    outputs=[],
                    payload={"event": "capture.frame_format_fallback", **payload},
                )
            except Exception:
                pass
        self._frame_format = coerced
        self._include_cursor = bool(capture_cfg.get("include_cursor", False))
        self._include_cursor_shape = bool(capture_cfg.get("include_cursor_shape", True))
        self._lossless = self._frame_format in {"rgb", "png"}
        backpressure_cfg = config.get("backpressure", {})
        self._rate_lock = threading.Lock()
        self._fps_target = int(capture_cfg.get("fps_target", backpressure_cfg.get("max_fps", 30)))
        self._bitrate_kbps = int(backpressure_cfg.get("max_bitrate_kbps", 8000))
        self._jpeg_quality = int(capture_cfg.get("jpeg_quality", 90))
        telemetry_cfg = config.get("runtime", {}).get("telemetry", {})
        self._telemetry_enabled = bool(telemetry_cfg.get("enabled", True))
        self._telemetry_interval_s = float(telemetry_cfg.get("emit_interval_s", 5))
        self._telemetry_last = 0.0
        self._telemetry_last_cpu = time.process_time()
        self._telemetry_last_wall = time.monotonic()
        self._telemetry_last_drops = 0
        self._last_frame_ts: float | None = None
        self._last_frame_interval_ms = 0.0
        self._last_lag_ms = 0.0

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
        runtime_cfg = self._config.get("runtime", {})
        suspend_workers = bool(runtime_cfg.get("mode_enforcement", {}).get("suspend_workers", True))
        silence_cfg = runtime_cfg.get("silence", {}) if isinstance(runtime_cfg, dict) else {}
        silence_enabled = bool(silence_cfg.get("enabled", True))
        silence_max_age_s = float(silence_cfg.get("max_capture_age_s", 15.0))
        silence_active_window_s = float(
            silence_cfg.get("active_window_s", runtime_cfg.get("active_window_s", 3))
        )
        silence_cooldown_s = float(silence_cfg.get("cooldown_s", 60.0))
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
        last_idle_seconds = 0.0
        last_activity_score = 0.0
        last_activity_reason: str | None = None
        backend = str(capture_cfg.get("backend", "mss"))
        disk_cfg = self._config.get("storage", {}).get("disk_pressure", {})
        warn_free = int(disk_cfg.get("warn_free_gb", 200))
        soft_free = int(disk_cfg.get("soft_free_gb", warn_free))
        critical_free = int(disk_cfg.get("critical_free_gb", 50))
        soft_mb = int(disk_cfg.get("watermark_soft_mb", 0) or 0)
        hard_mb = int(disk_cfg.get("watermark_hard_mb", 0) or 0)
        disk_pressure = DiskPressure(warn_free, soft_free, critical_free, soft_mb=soft_mb, hard_mb=hard_mb)
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
        frame_format = self._frame_format
        include_cursor = self._include_cursor
        include_cursor_shape = self._include_cursor_shape

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

        def _activity_snapshot() -> tuple[str, float, float, str | None]:
            idle_seconds = 0.0
            activity_score = 0.0
            activity_recent = False
            user_active = False
            if self._input_tracker is not None and hasattr(self._input_tracker, "activity_signal"):
                try:
                    signal = self._input_tracker.activity_signal()
                except Exception:
                    signal = {}
                if isinstance(signal, dict):
                    idle_seconds = float(signal.get("idle_seconds", 0.0))
                    activity_score = float(signal.get("activity_score", 0.0) or 0.0)
                    activity_recent = bool(signal.get("recent_activity", False))
                    user_active = bool(signal.get("user_active", idle_seconds < activity_window_s)) or activity_score >= 0.5
                    mode = "active" if user_active else "idle"
                    reason = None
                    if self._governor is not None:
                        try:
                            decision = self._governor.decide(
                                {
                                    "idle_seconds": idle_seconds,
                                    "user_active": user_active,
                                    "activity_score": activity_score,
                                    "activity_recent": activity_recent,
                                    "query_intent": False,
                                    "suspend_workers": suspend_workers,
                                }
                            )
                        except Exception:
                            decision = None
                        if decision is not None:
                            idle_seconds = float(decision.idle_seconds)
                            activity_score = float(decision.activity_score)
                            mode = "idle" if decision.mode == "IDLE_DRAIN" else "active"
                            reason = str(decision.reason)
                    return (mode, idle_seconds, activity_score, reason)
            if self._input_tracker is not None and hasattr(self._input_tracker, "idle_seconds"):
                try:
                    idle_seconds = float(self._input_tracker.idle_seconds())
                except Exception:
                    idle_seconds = 0.0
                user_active = idle_seconds < activity_window_s
                mode = "active" if user_active else "idle"
                reason = None
                if self._governor is not None:
                    try:
                        decision = self._governor.decide(
                            {
                                "idle_seconds": idle_seconds,
                                "user_active": user_active,
                                "activity_score": activity_score,
                                "activity_recent": activity_recent,
                                "query_intent": False,
                                "suspend_workers": suspend_workers,
                            }
                        )
                    except Exception:
                        decision = None
                    if decision is not None:
                        idle_seconds = float(decision.idle_seconds)
                        activity_score = float(decision.activity_score)
                        mode = "idle" if decision.mode == "IDLE_DRAIN" else "active"
                        reason = str(decision.reason)
                return (mode, idle_seconds, activity_score, reason)
            idle_seconds = float("inf") if assume_idle else 0.0
            user_active = idle_seconds < activity_window_s
            mode = "idle" if idle_seconds >= activity_window_s else "active"
            reason = None
            if self._governor is not None:
                try:
                    decision = self._governor.decide(
                        {
                            "idle_seconds": idle_seconds,
                            "user_active": user_active,
                            "activity_score": activity_score,
                            "activity_recent": activity_recent,
                            "query_intent": False,
                            "suspend_workers": suspend_workers,
                        }
                    )
                except Exception:
                    decision = None
                if decision is not None:
                    idle_seconds = float(decision.idle_seconds)
                    activity_score = float(decision.activity_score)
                    mode = "idle" if decision.mode == "IDLE_DRAIN" else "active"
                    reason = str(decision.reason)
            return (mode, idle_seconds, activity_score, reason)
        backend_used, frame_iter = _frame_iter(
            backend,
            fps_provider,
            frame_source=self._frame_source,
            jpeg_quality=jpeg_quality_provider if activity_enabled else int(jpeg_quality),
            frame_format=frame_format,
            monitor_index=monitor_index,
            resolution=resolution,
            include_cursor=include_cursor,
            include_cursor_shape=include_cursor_shape,
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
            if self._last_frame_ts is not None:
                interval = max(0.0, now - self._last_frame_ts)
                expected = 1.0 / max(1, int(fps_target))
                lag = max(0.0, interval - expected)
                self._last_frame_interval_ms = interval * 1000.0
                self._last_lag_ms = lag * 1000.0
            self._last_frame_ts = now
            if activity_enabled and (now - last_activity_check) >= max(0.2, activity_check_s):
                mode, idle_seconds, activity_score, activity_reason = _activity_snapshot()
                last_idle_seconds = float(idle_seconds)
                last_activity_score = float(activity_score)
                last_activity_reason = str(activity_reason) if activity_reason else None
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
                        "reason": str(activity_reason or ""),
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
            if silence_enabled and silence_max_age_s > 0:
                silence_idle_seconds = last_idle_seconds
                if not activity_enabled and self._input_tracker is not None:
                    try:
                        silence_idle_seconds = float(self._input_tracker.idle_seconds())
                    except Exception:
                        silence_idle_seconds = float("inf")
                user_active = silence_idle_seconds < silence_active_window_s
                last_output_age_s = None
                last_segment_id = None
                with self._last_output_lock:
                    last_segment_id = self._last_segment_id
                    if self._last_output_mono is not None:
                        last_output_age_s = max(0.0, now - self._last_output_mono)
                    else:
                        last_output_age_s = max(0.0, now - self._start_mono)
                if (
                    user_active
                    and last_output_age_s is not None
                    and last_output_age_s >= silence_max_age_s
                    and (now - self._last_silence_ts) >= silence_cooldown_s
                ):
                    self._last_silence_ts = now
                    silence_payload = {
                        "event": "capture.silence",
                        "idle_seconds": float(silence_idle_seconds),
                        "active_window_s": float(silence_active_window_s),
                        "last_capture_age_s": float(last_output_age_s),
                        "threshold_s": float(silence_max_age_s),
                        "segment_id": last_segment_id,
                        "run_id": str(self._config.get("runtime", {}).get("run_id", "")),
                        "plugin_id": self._plugin_id,
                    }
                    record_telemetry("capture.silence", silence_payload)
                    if self._logger is not None:
                        try:
                            self._logger.log("capture.silence", silence_payload)
                        except Exception:
                            pass
                    if self._event_builder is not None:
                        try:
                            self._event_builder.journal_event("capture.silence", silence_payload)
                            self._event_builder.ledger_entry(
                                "capture.silence",
                                inputs=[],
                                outputs=[],
                                payload={"event": "capture.silence", **silence_payload},
                            )
                        except Exception:
                            pass
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
                data_dir = self._config.get("storage", {}).get("data_dir", ".")
                free_bytes = _free_bytes(data_dir)
                free_gb = int(free_bytes // (1024 ** 3))
                level, changed = disk_pressure.evaluate(free_gb, free_bytes)
                if changed:
                    pressure_payload: dict[str, Any] = {
                        "level": level,
                        "free_gb": int(free_gb),
                        "free_bytes": int(free_bytes),
                        "warn_gb": int(warn_free),
                        "soft_gb": int(soft_free),
                        "critical_gb": int(critical_free),
                        "soft_mb": int(soft_mb),
                        "hard_mb": int(hard_mb),
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
                        "free_bytes": int(free_bytes),
                        "threshold_mb": int(hard_mb) if hard_mb > 0 else None,
                    }
                    self._event_builder.journal_event("disk.critical", critical_payload)
                    self._event_builder.ledger_entry(
                        "disk.critical",
                        inputs=[],
                        outputs=[],
                        payload={"event": "disk.critical", **critical_payload},
                    )
                    if hard_mb > 0 and free_bytes <= (hard_mb * 1024 * 1024):
                        halt_payload = {
                            "reason": "disk_low",
                            "free_bytes": int(free_bytes),
                            "threshold_mb": int(hard_mb),
                        }
                        self._event_builder.journal_event("capture.halt_disk", halt_payload)
                        self._event_builder.ledger_entry(
                            "capture.halt_disk",
                            inputs=[],
                            outputs=[],
                            payload={"event": "capture.halt_disk", **halt_payload},
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
                {
                    "queue_depth": int(queue_depth),
                    "now": now,
                    "mode": str(activity_mode or ""),
                    "idle_seconds": float(last_idle_seconds),
                    "activity_score": float(last_activity_score),
                },
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
                self._throttle_events += 1
                throttle_payload = {
                    "event": "capture.throttle",
                    "fps_prev": int(fps_target),
                    "fps_target": int(updated_fps),
                    "bitrate_prev_kbps": int(bitrate_kbps),
                    "bitrate_target_kbps": int(updated_bitrate),
                    "queue_depth": int(queue_depth),
                    "mode": str(activity_mode or ""),
                    "idle_seconds": float(last_idle_seconds),
                    "activity_score": float(last_activity_score),
                    "run_id": str(self._config.get("runtime", {}).get("run_id", "")),
                    "plugin_id": self._plugin_id,
                }
                record_telemetry("capture.throttle", throttle_payload)
                if self._event_builder is not None:
                    try:
                        self._event_builder.journal_event("capture.throttle", throttle_payload)
                    except Exception:
                        pass
                fps_target = updated_fps
                bitrate_kbps = updated_bitrate
                with self._rate_lock:
                    self._fps_target = fps_target
                    self._bitrate_kbps = bitrate_kbps

            self._emit_capture_telemetry(
                now_mono=now,
                mode=str(activity_mode or "unknown"),
                idle_seconds=float(last_idle_seconds),
                activity_score=float(last_activity_score),
                reason=last_activity_reason,
                queue_depth=int(queue_depth),
            )

        # Signal end of stream
        frame_queue.put(STOP_SENTINEL)

    def _encode_loop(self) -> None:
        capture_cfg = self._config.get("capture", {}).get("video", {})
        segment_seconds = int(capture_cfg.get("segment_seconds", 60))
        container_type = self._container_type
        encoder = str(capture_cfg.get("encoder", "cpu"))
        ffmpeg_path = self._ffmpeg_path
        frame_format = self._frame_format
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
                    frame_format=frame_format,
                    fsync_policy=fsync_policy,
                    job_limits=self._capture_job_limits,
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
        write_start = time.perf_counter()
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
            "ts_utc": artifact.ts_start_utc,
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
            "frame_format": self._frame_format,
            "lossless": bool(self._lossless),
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
        try:
            content_size = os.path.getsize(artifact.path)
        except Exception:
            content_size = None
        if content_size is not None:
            metadata["content_size"] = int(content_size)
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
        cursor = None
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

        try:
            self._event_builder.capture_stage(
                artifact.segment_id,
                metadata.get("record_type", "evidence.capture.segment"),
                ts_utc=artifact.ts_start_utc,
                payload={
                    "backend": backend,
                    "frame_count": int(artifact.frame_count),
                    "ts_start_utc": artifact.ts_start_utc,
                    "ts_end_utc": artifact.ts_end_utc,
                },
            )
        except Exception:
            pass

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
            try:
                self._event_builder.capture_commit(
                    artifact.segment_id,
                    metadata.get("record_type", "evidence.capture.segment"),
                    ts_utc=artifact.ts_end_utc or artifact.ts_start_utc,
                    payload={
                        "content_hash": content_hash,
                        "payload_hash": metadata.get("payload_hash"),
                        "content_size": metadata.get("content_size"),
                    },
                )
            except Exception:
                pass
            seal_payload = {
                "event": "segment.sealed",
                "segment_id": artifact.segment_id,
                "content_hash": content_hash,
                "payload_hash": metadata.get("payload_hash"),
            }
            container = metadata.get("container")
            if isinstance(container, dict) and container.get("index") is not None:
                seal_payload["container_index_hash"] = sha256_canonical(container.get("index"))
            self._event_builder.ledger_entry(
                "segment.seal",
                inputs=[artifact.segment_id],
                outputs=[],
                payload=seal_payload,
                ts_utc=artifact.ts_end_utc,
            )
            with self._last_output_lock:
                self._last_output_mono = time.monotonic()
                self._last_segment_id = artifact.segment_id
            write_ms = int(max(0.0, (time.perf_counter() - write_start) * 1000.0))
            telemetry_payload = {
                "ts_utc": artifact.ts_end_utc or artifact.ts_start_utc,
                "record_id": artifact.segment_id,
                "record_type": "evidence.capture.segment",
                "output_bytes": int(metadata.get("content_size") or 0),
                "frame_count": int(metadata.get("frame_count") or 0),
                "write_ms": write_ms,
                "backend": backend,
            }
            record_telemetry("capture.output", telemetry_payload)
            if self._plugin_id:
                record_telemetry(f"plugin.{self._plugin_id}", telemetry_payload)
        except Exception as exc:
            failure_payload = {
                "segment_id": artifact.segment_id,
                "backend": backend,
            }
            if hasattr(self._event_builder, "failure_event"):
                self._event_builder.failure_event(
                    "capture.partial_failure",
                    stage="storage.write",
                    error=exc,
                    inputs=[artifact.segment_id],
                    outputs=[],
                    payload=failure_payload,
                    ts_utc=artifact.ts_start_utc,
                    retryable=False,
                )
            else:
                failure_payload.update({"event": "capture.partial_failure", "error": str(exc)})
                self._event_builder.journal_event(
                    "capture.partial_failure",
                    failure_payload,
                    ts_utc=artifact.ts_start_utc,
                )
                self._event_builder.ledger_entry(
                    "capture.partial_failure",
                    inputs=[artifact.segment_id],
                    outputs=[],
                    payload=failure_payload,
                    ts_utc=artifact.ts_start_utc,
                )
            return
        try:
            os.remove(artifact.path)
        except FileNotFoundError:
            pass

    def _emit_capture_telemetry(
        self,
        *,
        now_mono: float,
        mode: str,
        idle_seconds: float,
        activity_score: float,
        reason: str | None,
        queue_depth: int,
    ) -> None:
        if not self._telemetry_enabled:
            return
        interval = max(0.5, float(self._telemetry_interval_s))
        if mode == "active":
            interval = max(interval, float(self._telemetry_interval_s) * 3.0)
        if now_mono - self._telemetry_last < interval:
            return
        cpu_now = time.process_time()
        wall_now = time.monotonic()
        cpu_delta = max(0.0, cpu_now - self._telemetry_last_cpu)
        wall_delta = max(0.001, wall_now - self._telemetry_last_wall)
        cpu_pct = min(100.0, (cpu_delta / wall_delta) * 100.0)
        with self._drops_lock:
            drops_total = int(self._drops_total)
            queue_depth_max = int(self._queue_depth_max)
        self._queue_depth_samples.append(int(queue_depth))
        self._lag_samples.append(float(self._last_lag_ms))
        queue_p95 = percentile(list(self._queue_depth_samples), 95)
        lag_p95 = percentile(list(self._lag_samples), 95)
        last_capture_age_s = None
        last_segment_id = None
        with self._last_output_lock:
            if self._last_output_mono is not None:
                last_capture_age_s = max(0.0, now_mono - self._last_output_mono)
            last_segment_id = self._last_segment_id
        drops_delta = drops_total - int(self._telemetry_last_drops)
        if drops_delta < 0:
            drops_delta = drops_total
        payload = {
            "mode": mode,
            "reason": reason or "",
            "idle_seconds": float(idle_seconds),
            "activity_score": float(activity_score),
            "queue_depth": int(queue_depth),
            "queue_depth_max": int(queue_depth_max),
            "queue_depth_p95": None if queue_p95 is None else float(queue_p95),
            "drops_total": int(drops_total),
            "drops_delta": int(drops_delta),
            "lag_ms": float(self._last_lag_ms),
            "lag_p95_ms": None if lag_p95 is None else float(lag_p95),
            "frame_interval_ms": float(self._last_frame_interval_ms),
            "cpu_pct": float(round(cpu_pct, 3)),
            "fps_target": int(self._fps_target),
            "bitrate_kbps": int(self._bitrate_kbps),
            "jpeg_quality": int(self._jpeg_quality),
            "backend": str(self._backend_used),
            "last_capture_age_s": None if last_capture_age_s is None else float(round(last_capture_age_s, 3)),
            "last_segment_id": last_segment_id,
            "run_id": str(self._config.get("runtime", {}).get("run_id", "")),
            "plugin_id": self._plugin_id,
            "throttle_events_total": int(self._throttle_events),
        }
        self._telemetry_last = now_mono
        self._telemetry_last_cpu = cpu_now
        self._telemetry_last_wall = wall_now
        self._telemetry_last_drops = int(drops_total)
        record_telemetry("capture", payload)
        if self._event_builder is not None:
            try:
                self._event_builder.journal_event("telemetry.capture", payload)
            except Exception:
                pass
        if self._logger is not None:
            try:
                self._logger.log("telemetry.capture", payload)
            except Exception:
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
    free = _free_bytes(path)
    return int(free // (1024 ** 3))


def _free_bytes(path: str) -> int:
    _total, _used, free = shutil.disk_usage(path)
    return int(free)


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
    if container_type == "ffmpeg_lossless":
        path = ffmpeg_path or shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
        if not path:
            return "zip", None
        return "ffmpeg_lossless", path
    return container_type, None


def _resolve_frame_format(frame_format: str, requested_container: str, resolved_container: str) -> str:
    mode = str(frame_format or "auto").strip().lower()
    if mode not in {"auto", "jpeg", "png", "rgb"}:
        mode = "auto"
    if mode != "auto":
        return mode
    if requested_container == "ffmpeg_lossless":
        return "rgb" if resolved_container == "ffmpeg_lossless" else "png"
    if resolved_container == "zip":
        return "jpeg"
    return "jpeg"


def _coerce_frame_format(frame_format: str, container_type: str) -> str:
    mode = str(frame_format or "jpeg").strip().lower()
    if container_type in {"avi_mjpeg", "ffmpeg_mp4"}:
        return "jpeg"
    if container_type == "ffmpeg_lossless":
        return "rgb"
    if container_type == "zip":
        return "png" if mode == "rgb" else (mode if mode in {"jpeg", "png"} else "png")
    return mode


def _frame_iter(
    backend: str,
    fps_provider: Callable[[], int],
    *,
    frame_source: Any | None,
    jpeg_quality: int | Callable[[], int],
    frame_format: str,
    monitor_index: int,
    resolution: str | None,
    include_cursor: bool,
    include_cursor_shape: bool,
) -> tuple[str, Any]:
    if backend == "auto":
        try:
            return "dxcam", _dxcam_frames(
                fps_provider,
                jpeg_quality=jpeg_quality,
                frame_format=frame_format,
                monitor_index=monitor_index,
                resolution=resolution,
                include_cursor=include_cursor,
                include_cursor_shape=include_cursor_shape,
            )
        except Exception:
            return "mss", iter_screenshots(
                fps_provider,
                frame_source=frame_source,
                jpeg_quality=jpeg_quality,
                frame_format=frame_format,
                monitor_index=monitor_index,
                resolution=resolution,
                include_cursor=include_cursor,
                include_cursor_shape=include_cursor_shape,
            )
    if backend == "dxcam":
        try:
            return "dxcam", _dxcam_frames(
                fps_provider,
                jpeg_quality=jpeg_quality,
                frame_format=frame_format,
                monitor_index=monitor_index,
                resolution=resolution,
                include_cursor=include_cursor,
                include_cursor_shape=include_cursor_shape,
            )
        except Exception:
            return "mss", iter_screenshots(
                fps_provider,
                frame_source=frame_source,
                jpeg_quality=jpeg_quality,
                frame_format=frame_format,
                monitor_index=monitor_index,
                resolution=resolution,
                include_cursor=include_cursor,
                include_cursor_shape=include_cursor_shape,
            )
    return backend, iter_screenshots(
        fps_provider,
        frame_source=frame_source,
        jpeg_quality=jpeg_quality,
        frame_format=frame_format,
        monitor_index=monitor_index,
        resolution=resolution,
        include_cursor=include_cursor,
        include_cursor_shape=include_cursor_shape,
    )


def _dxcam_frames(
    fps_provider: Callable[[], int],
    *,
    jpeg_quality: int | Callable[[], int],
    frame_format: str,
    monitor_index: int,
    resolution: str | None,
    include_cursor: bool,
    include_cursor_shape: bool,
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
    frame_mode = str(frame_format or "jpeg").strip().lower()
    if frame_mode not in {"jpeg", "png", "rgb"}:
        frame_mode = "jpeg"
    mon_left = 0
    mon_top = 0
    if include_cursor:
        try:
            layout = list_monitors() or []
            for entry in layout:
                if int(entry.get("index", -1)) == int(monitor_index):
                    mon_left = int(entry.get("left", 0))
                    mon_top = int(entry.get("top", 0))
                    break
        except Exception:
            mon_left = 0
            mon_top = 0
    current_cursor: Callable[[], "CursorInfo | None"] | None = None
    cursor_shape: Callable[[int], "CursorShape | None"] | None = None
    if include_cursor:
        try:
            from autocapture_nx.windows.win_cursor import current_cursor as _current_cursor, cursor_shape as _cursor_shape
        except Exception:
            pass
        else:
            current_cursor = _current_cursor
            cursor_shape = _cursor_shape
    cursor_handle = None
    cursor_cached = None

    def _cursor_shape_cached(handle: int):
        nonlocal cursor_handle, cursor_cached
        if not handle or cursor_shape is None:
            return None
        if cursor_handle != handle or cursor_cached is None:
            cursor_handle = handle
            cursor_cached = cursor_shape(handle)
        return cursor_cached

    while True:
        frame = cam.grab()
        if frame is None:
            time.sleep(1.0 / max(1, int(fps_provider())))
            continue
        img = Image.fromarray(frame)
        if target_size and (img.width, img.height) != target_size:
            img = img.resize(target_size)
        if include_cursor and current_cursor is not None:
            cursor_info = current_cursor()
            if cursor_info is not None and cursor_info.visible:
                shape = None
                if include_cursor_shape:
                    shape = _cursor_shape_cached(cursor_info.handle)
                if shape is not None:
                    offset_x = int(cursor_info.x) - mon_left
                    offset_y = int(cursor_info.y) - mon_top
                    if target_size and frame.shape[1] and frame.shape[0]:
                        scale_x = target_size[0] / frame.shape[1]
                        scale_y = target_size[1] / frame.shape[0]
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
        from io import BytesIO

        bio = BytesIO()
        if frame_mode == "rgb":
            data = img.tobytes()
        elif frame_mode == "png":
            img.save(bio, format="PNG", compress_level=3, optimize=False)
            data = bio.getvalue()
        else:
            quality = jpeg_quality() if callable(jpeg_quality) else jpeg_quality
            img.save(bio, format="JPEG", quality=int(quality))
            data = bio.getvalue()
        yield Frame(ts_utc=_iso_utc(), data=data, width=img.width, height=img.height, ts_monotonic=time.monotonic())
