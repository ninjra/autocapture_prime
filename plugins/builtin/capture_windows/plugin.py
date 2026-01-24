"""Windows screen capture plugin using mss + Pillow."""

from __future__ import annotations

import os
import threading
import time
import zipfile
from io import BytesIO
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.windows.win_capture import iter_screenshots


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
        fps = int(capture_cfg.get("fps_target", 30))
        segment_seconds = int(capture_cfg.get("segment_seconds", 60))
        disk_cfg = self.context.config.get("storage", {}).get("disk_pressure", {})
        warn_free = int(disk_cfg.get("warn_free_gb", 200))
        critical_free = int(disk_cfg.get("critical_free_gb", 50))
        storage_media = self.context.get_capability("storage.media")
        storage_meta = self.context.get_capability("storage.metadata")
        journal = self.context.get_capability("journal.writer")
        ledger = self.context.get_capability("ledger.writer")
        anchor = self.context.get_capability("anchor.writer")
        backpressure = self.context.get_capability("capture.backpressure")
        logger = self.context.get_capability("observability.logger")

        frames = []
        segment_start = time.time()
        sequence = 0

        for frame in iter_screenshots(fps):
            if self._stop.is_set():
                break
            frames.append(frame)
            now = time.time()
            if now - segment_start >= segment_seconds:
                if not self._check_disk(logger, journal, ledger, anchor, warn_free, critical_free):
                    self._stop.set()
                    break
                self._flush_segment(frames, storage_media, storage_meta, journal, ledger, anchor, sequence)
                frames = []
                sequence += 1
                segment_start = now

            # Apply backpressure based on queue depth (frames length)
            update = backpressure.adjust({"queue_depth": len(frames), "now": now}, {"fps_target": fps, "bitrate_kbps": 8000})
            fps = int(update.get("fps_target", fps))

    def _flush_segment(self, frames, storage_media, storage_meta, journal, ledger, anchor, sequence):
        if not frames:
            return
        segment_id = f"segment_{sequence}"
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for idx, frame in enumerate(frames):
                name = f"frame_{idx}.jpg"
                zf.writestr(name, frame.data)
        storage_media.put(segment_id, buf.getvalue())
        metadata = {
            "segment_id": segment_id,
            "ts_utc": frames[0].ts_utc,
            "frame_count": len(frames),
            "width": frames[0].width,
            "height": frames[0].height,
        }
        storage_meta.put(segment_id, metadata)
        journal.append(
            {
                "schema_version": 1,
                "event_id": segment_id,
                "sequence": sequence,
                "ts_utc": frames[0].ts_utc,
                "tzid": "UTC",
                "offset_minutes": 0,
                "event_type": "capture.segment",
                "payload": metadata,
            }
        )
        ledger_hash = ledger.append(
            {
                "schema_version": 1,
                "entry_id": segment_id,
                "ts_utc": frames[0].ts_utc,
                "stage": "capture",
                "inputs": [],
                "outputs": [segment_id],
                "policy_snapshot_hash": sha256_text(dumps(self.context.config)),
                "payload": metadata,
            }
        )
        anchor.anchor(ledger_hash)

    def _check_disk(self, logger, journal, ledger, anchor, warn_free, critical_free) -> bool:
        import shutil
        from datetime import datetime, timezone

        total, used, free = shutil.disk_usage(self.context.config.get("storage", {}).get("data_dir", "."))
        free_gb = free / (1024 ** 3)
        if free_gb < critical_free:
            payload = {"free_gb": free_gb, "threshold_gb": critical_free}
            logger.log("disk.critical", payload)
            journal.append(
                {
                    "schema_version": 1,
                    "event_id": "disk_critical",
                    "sequence": 0,
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "tzid": "UTC",
                    "offset_minutes": 0,
                    "event_type": "disk.critical",
                    "payload": payload,
                }
            )
            ledger_hash = ledger.append(
                {
                    "schema_version": 1,
                    "entry_id": "disk_critical",
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "stage": "runtime",
                    "inputs": [],
                    "outputs": ["disk_critical"],
                    "policy_snapshot_hash": sha256_text(dumps(self.context.config)),
                    "payload": payload,
                }
            )
            anchor.anchor(ledger_hash)
            return False
        if free_gb < warn_free:
            logger.log("disk.warn", {"free_gb": free_gb, "threshold_gb": warn_free})
        return True


def create_plugin(plugin_id: str, context: PluginContext) -> CaptureWindows:
    return CaptureWindows(plugin_id, context)
