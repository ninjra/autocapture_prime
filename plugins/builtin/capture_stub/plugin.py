"""Replay/synthetic capture plugin for non-Windows environments."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator

from autocapture_nx.capture.pipeline import CapturePipeline
from autocapture_nx.kernel.ids import ensure_run_id
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.windows.win_capture import Frame

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class CaptureStub(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pipeline: CapturePipeline | None = None

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

        pipeline = CapturePipeline(
            self.context.config,
            storage_media=storage_media,
            storage_meta=storage_meta,
            event_builder=event_builder,
            backpressure=backpressure,
            logger=logger,
            window_tracker=window_tracker,
            input_tracker=input_tracker,
            stop_event=self._stop,
            frame_source=self._frame_source(),
        )
        self._pipeline = pipeline
        pipeline.start()
        pipeline.join()

    def _frame_source(self) -> Iterator[Frame]:
        cfg = self.context.config.get("capture", {}).get("stub", {})
        frames_dir = str(cfg.get("frames_dir", "")).strip()
        loop = bool(cfg.get("loop", False))
        max_frames = int(cfg.get("max_frames", 0))
        frame_width = int(cfg.get("frame_width", 1280))
        frame_height = int(cfg.get("frame_height", 720))
        jpeg_quality = int(cfg.get("jpeg_quality", 90))

        if frames_dir:
            root = Path(frames_dir)
            if not root.is_absolute():
                root = resolve_repo_path(root)
            if root.exists():
                paths = [p for p in sorted(root.iterdir()) if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}]
                if paths:
                    return _file_frames(paths, loop=loop, max_frames=max_frames, jpeg_quality=jpeg_quality)

        return _synthetic_frames(
            frame_width,
            frame_height,
            loop=loop,
            max_frames=max_frames,
            jpeg_quality=jpeg_quality,
        )


def _optional_capability(context: PluginContext, name: str):
    try:
        return context.get_capability(name)
    except Exception:
        return None


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode_jpeg(image, *, jpeg_quality: int) -> bytes:
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=int(jpeg_quality))
    return buf.getvalue()


def _file_frames(
    paths: list[Path],
    *,
    loop: bool,
    max_frames: int,
    jpeg_quality: int,
) -> Iterator[Frame]:
    from PIL import Image

    emitted = 0
    while True:
        for path in paths:
            if max_frames and emitted >= max_frames:
                return
            try:
                img = Image.open(path).convert("RGB")
            except Exception:
                continue
            data = _encode_jpeg(img, jpeg_quality=jpeg_quality)
            emitted += 1
            yield Frame(
                ts_utc=_iso_utc(),
                data=data,
                width=img.width,
                height=img.height,
                ts_monotonic=None,
            )
        if not loop:
            break


def _synthetic_frames(
    width: int,
    height: int,
    *,
    loop: bool,
    max_frames: int,
    jpeg_quality: int,
) -> Iterator[Frame]:
    from PIL import Image, ImageDraw

    width = max(1, int(width))
    height = max(1, int(height))
    emitted = 0
    while True:
        if max_frames and emitted >= max_frames:
            return
        img = Image.new("RGB", (width, height), (120, 120, 120))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, width - 1, height - 1), outline=(40, 40, 40))
        draw.text((10, 10), f"stub-frame-{emitted}", fill=(240, 240, 240))
        data = _encode_jpeg(img, jpeg_quality=jpeg_quality)
        emitted += 1
        yield Frame(
            ts_utc=_iso_utc(),
            data=data,
            width=width,
            height=height,
            ts_monotonic=None,
        )
        if not loop and max_frames and emitted >= max_frames:
            return


def create_plugin(plugin_id: str, context: PluginContext) -> CaptureStub:
    return CaptureStub(plugin_id, context)
