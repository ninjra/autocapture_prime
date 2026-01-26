"""Windows screen capture plugin using mss + Pillow."""

from __future__ import annotations

import os
import threading
import time
import zipfile
from dataclasses import dataclass
from typing import Any

from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.windows.win_capture import Frame, iter_screenshots


@dataclass
class _SegmentWriter:
    segment_id: str
    path: str
    zip_file: zipfile.ZipFile
    frame_count: int = 0
    first_ts: str | None = None
    width: int = 0
    height: int = 0

    def add_frame(self, frame: Frame) -> None:
        if self.frame_count == 0:
            self.first_ts = frame.ts_utc
            self.width = frame.width
            self.height = frame.height
        name = f"frame_{self.frame_count}.jpg"
        self.zip_file.writestr(name, frame.data)
        self.frame_count += 1

    def close(self) -> None:
        self.zip_file.close()


class CaptureWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def capabilities(self) -> dict[str, Any]:
        return {"capture.source": self}

    def start(self) -> None:
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
        capture_cfg = self.context.config.get("capture", {}).get("video", {})
        backend = capture_cfg.get("backend", "mss")
        if backend != "mss":
            raise RuntimeError(f"Unsupported capture backend: {backend}")
        backpressure_cfg = self.context.config.get("backpressure", {})
        fps_target = int(capture_cfg.get("fps_target", backpressure_cfg.get("max_fps", 30)))
        bitrate_kbps = int(backpressure_cfg.get("max_bitrate_kbps", 8000))
        segment_seconds = int(capture_cfg.get("segment_seconds", 60))
        disk_cfg = self.context.config.get("storage", {}).get("disk_pressure", {})
        warn_free = int(disk_cfg.get("warn_free_gb", 200))
        critical_free = int(disk_cfg.get("critical_free_gb", 50))
        storage_media = self.context.get_capability("storage.media")
        storage_meta = self.context.get_capability("storage.metadata")
        event_builder = self.context.get_capability("event.builder")
        backpressure = self.context.get_capability("capture.backpressure")
        logger = self.context.get_capability("observability.logger")
        run_id = ensure_run_id(self.context.config)

        spool_dir = self.context.config.get("storage", {}).get("spool_dir", "data/spool")
        os.makedirs(spool_dir, exist_ok=True)
        segment: _SegmentWriter | None = None
        segment_start = time.monotonic()
        sequence = 0
        flush_on_exit = True

        def fps_provider() -> int:
            return fps_target

        for frame in iter_screenshots(fps_provider):
            if self._stop.is_set():
                break
            if segment is None:
                segment = self._open_segment(spool_dir, run_id, sequence)
                segment_start = time.monotonic()
            segment.add_frame(frame)
            now = time.monotonic()
            if time.monotonic() - segment_start >= segment_seconds:
                if not self._check_disk(logger, event_builder, warn_free, critical_free):
                    flush_on_exit = False
                    self._stop.set()
                    break
                self._flush_segment(segment, storage_media, storage_meta, event_builder)
                segment = None
                sequence += 1

            # Apply backpressure based on queue depth (frames length)
            queue_depth = segment.frame_count if segment else 0
            update = backpressure.adjust({"queue_depth": int(queue_depth), "now": now}, {"fps_target": fps_target, "bitrate_kbps": bitrate_kbps})
            updated_fps = int(update.get("fps_target", fps_target))
            updated_bitrate = int(update.get("bitrate_kbps", bitrate_kbps))
            if updated_fps != fps_target or updated_bitrate != bitrate_kbps:
                self._log_rate_change(
                    logger,
                    event_builder,
                    fps_target,
                    updated_fps,
                    bitrate_kbps,
                    updated_bitrate,
                    queue_depth,
                )
                fps_target = updated_fps
                bitrate_kbps = updated_bitrate

        if segment and segment.frame_count:
            if flush_on_exit:
                self._flush_segment(segment, storage_media, storage_meta, event_builder)
            else:
                segment.close()
                if os.path.exists(segment.path):
                    os.remove(segment.path)

    def _open_segment(self, spool_dir: str, run_id: str, sequence: int) -> _SegmentWriter:
        segment_id = prefixed_id(run_id, "segment", sequence)
        safe_name = segment_id.replace("/", "_")
        path = os.path.join(spool_dir, f"{safe_name}.zip")
        zip_file = zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED)
        return _SegmentWriter(segment_id=segment_id, path=path, zip_file=zip_file)

    def _flush_segment(self, segment: _SegmentWriter, storage_media, storage_meta, event_builder):
        if segment.frame_count == 0:
            segment.close()
            if os.path.exists(segment.path):
                os.remove(segment.path)
            return
        from datetime import datetime, timezone

        segment_ts = segment.first_ts or datetime.now(timezone.utc).isoformat()
        segment.close()
        with open(segment.path, "rb") as handle:
            if hasattr(storage_media, "put_stream"):
                storage_media.put_stream(segment.segment_id, handle)
            else:
                storage_media.put(segment.segment_id, handle.read())
        os.remove(segment.path)
        metadata = {
            "record_type": "evidence.capture.segment",
            "segment_id": segment.segment_id,
            "ts_utc": segment_ts,
            "frame_count": int(segment.frame_count),
            "width": int(segment.width),
            "height": int(segment.height),
        }
        storage_meta.put(segment.segment_id, metadata)
        event_builder.journal_event(
            "capture.segment",
            metadata,
            event_id=segment.segment_id,
            ts_utc=segment_ts,
        )
        event_builder.ledger_entry(
            "capture",
            inputs=[],
            outputs=[segment.segment_id],
            payload=metadata,
            entry_id=segment.segment_id,
            ts_utc=segment_ts,
        )

    def _check_disk(self, logger, event_builder, warn_free, critical_free) -> bool:
        import shutil

        total, used, free = shutil.disk_usage(self.context.config.get("storage", {}).get("data_dir", "."))
        free_gb = int(free // (1024 ** 3))
        if free_gb < critical_free:
            payload = {"free_gb": free_gb, "threshold_gb": int(critical_free)}
            logger.log("disk.critical", payload)
            event_id = event_builder.journal_event("disk.critical", payload)
            event_builder.ledger_entry(
                "runtime",
                inputs=[],
                outputs=[event_id],
                payload=payload,
                entry_id=event_id,
            )
            return False
        if free_gb < warn_free:
            logger.log("disk.warn", {"free_gb": free_gb, "threshold_gb": int(warn_free)})
        return True

    def _log_rate_change(
        self,
        logger,
        event_builder,
        fps_prev,
        fps_target,
        bitrate_prev,
        bitrate_target,
        queue_depth,
    ) -> None:
        from datetime import datetime, timezone

        payload = {
            "fps_prev": int(fps_prev),
            "fps_target": int(fps_target),
            "bitrate_prev_kbps": int(bitrate_prev),
            "bitrate_target_kbps": int(bitrate_target),
            "queue_depth": int(queue_depth),
        }
        logger.log("capture.rate_change", payload)
        event_builder.journal_event(
            "capture.rate_change",
            payload,
            ts_utc=datetime.now(timezone.utc).isoformat(),
        )


def create_plugin(plugin_id: str, context: PluginContext) -> CaptureWindows:
    return CaptureWindows(plugin_id, context)
