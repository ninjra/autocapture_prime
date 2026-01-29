"""Windows screen capture plugin using staged pipeline."""

from __future__ import annotations

import threading
from typing import Any

from autocapture_nx.capture.pipeline import CapturePipeline
from autocapture_nx.kernel.ids import ensure_run_id
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class CaptureWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pipeline: CapturePipeline | None = None

    def capabilities(self) -> dict[str, Any]:
        return {"capture.source": self}

    def start(self) -> None:
        capture_cfg = self.context.config.get("capture", {}).get("video", {})
        if not bool(capture_cfg.get("enabled", True)):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._pipeline is not None:
            self._pipeline.stop()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        ensure_run_id(self.context.config)
        storage_media = self.context.get_capability("storage.media")
        storage_meta = self.context.get_capability("storage.metadata")
        event_builder = self.context.get_capability("event.builder")
        backpressure = self.context.get_capability("capture.backpressure")
        logger = self.context.get_capability("observability.logger")
        window_tracker = _optional_capability(self.context, "window.metadata")
        input_tracker = _optional_capability(self.context, "tracking.input")
        governor = _optional_capability(self.context, "runtime.governor")

        pipeline = CapturePipeline(
            self.context.config,
            plugin_id=self.plugin_id,
            storage_media=storage_media,
            storage_meta=storage_meta,
            event_builder=event_builder,
            backpressure=backpressure,
            logger=logger,
            window_tracker=window_tracker,
            input_tracker=input_tracker,
            governor=governor,
            stop_event=self._stop,
        )
        self._pipeline = pipeline
        pipeline.start()
        pipeline.join()

    def _check_disk(self, logger, event_builder, warn_free: int, critical_free: int) -> bool:
        import shutil

        _total, _used, free = shutil.disk_usage(self.context.config.get("storage", {}).get("data_dir", "."))
        free_gb = int(free // (1024 ** 3))
        if free_gb < critical_free:
            payload = {"free_gb": int(free_gb), "threshold_gb": int(critical_free)}
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
            logger.log("disk.warn", {"free_gb": int(free_gb), "threshold_gb": int(warn_free)})
        return True


def _optional_capability(context: PluginContext, name: str) -> Any | None:
    try:
        return context.get_capability(name)
    except Exception:
        return None


def create_plugin(plugin_id: str, context: PluginContext) -> CaptureWindows:
    return CaptureWindows(plugin_id, context)
