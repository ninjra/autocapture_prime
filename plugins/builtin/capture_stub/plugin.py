"""Fallback capture plugin with optional replay/synthetic mode."""

from __future__ import annotations

import threading
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator

from autocapture_nx.capture.pipeline import CapturePipeline
from autocapture_nx.kernel.ids import ensure_run_id
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.windows.win_capture import Frame

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class CaptureBasic(PluginBase):
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
        governor = _optional_capability(self.context, "runtime.governor")

        frame_source = self._frame_source()
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
            frame_source=frame_source,
        )
        self._pipeline = pipeline
        pipeline.start()
        pipeline.join()

    def _frame_source(self) -> Iterator[Frame] | None:
        cfg = self.context.config.get("capture", {}).get("stub", {})
        frames_dir = str(cfg.get("frames_dir", "")).strip()
        loop = bool(cfg.get("loop", False))
        max_frames = int(cfg.get("max_frames", 0))
        frame_width = int(cfg.get("frame_width", 1280))
        frame_height = int(cfg.get("frame_height", 720))
        jpeg_quality = int(cfg.get("jpeg_quality", 90))
        frame_format = str(cfg.get("frame_format", "")).strip().lower()
        timestamp_source = str(cfg.get("timestamp_source", "now") or "now").strip().lower()
        if not frame_format or frame_format == "auto":
            frame_format = "png" if bool(cfg.get("lossless", False)) else "jpeg"
        if frame_format not in {"jpeg", "png", "rgb"}:
            frame_format = "jpeg"

        if frames_dir:
            root = Path(frames_dir)
            if not root.is_absolute():
                root = resolve_repo_path(root)
            if root.exists():
                paths = [p for p in sorted(root.iterdir()) if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}]
                if paths:
                    return _file_frames(
                        paths,
                        loop=loop,
                        max_frames=max_frames,
                        jpeg_quality=jpeg_quality,
                        frame_format=frame_format,
                        timestamp_source=timestamp_source,
                    )

        if max_frames > 0:
            return _synthetic_frames(
                frame_width,
                frame_height,
                loop=loop,
                max_frames=max_frames,
                jpeg_quality=jpeg_quality,
                frame_format=frame_format,
            )
        return None


def _optional_capability(context: PluginContext, name: str):
    try:
        return context.get_capability(name)
    except Exception:
        return None


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


_TS_PATTERNS = (
    "%Y-%m-%d %H%M%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y_%m_%d %H%M%S",
    "%Y_%m_%d_%H%M%S",
    "%Y%m%d_%H%M%S",
    "%Y%m%d %H%M%S",
)


def _timestamp_from_filename(name: str) -> str | None:
    if not name:
        return None
    candidates = re.findall(r"\d{4}[-_]\d{2}[-_]\d{2}[ T_-]\d{2}[:.\-]?\d{2}[:.\-]?\d{2}", name)
    for raw in candidates:
        normalized = raw.replace("T", " ").replace("_", " ").replace("-", "-").replace(".", ":")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        for pattern in _TS_PATTERNS:
            try:
                dt = datetime.strptime(normalized, pattern)
            except Exception:
                continue
            return dt.replace(tzinfo=timezone.utc).isoformat()
    return None


def _frame_ts_utc(path: Path, *, source: str) -> str:
    mode = str(source or "now").strip().lower()
    if mode == "filename":
        ts = _timestamp_from_filename(path.stem) or _timestamp_from_filename(path.name)
        if ts:
            return ts
    if mode == "mtime":
        try:
            ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            return ts
        except Exception:
            pass
    return _iso_utc()


def _encode_jpeg(image, *, jpeg_quality: int) -> bytes:
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=int(jpeg_quality))
    return buf.getvalue()


def _encode_png(image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG", compress_level=3, optimize=False)
    return buf.getvalue()


def _encode_frame(image, *, frame_format: str, jpeg_quality: int) -> bytes:
    mode = str(frame_format or "jpeg").strip().lower()
    if mode == "rgb":
        return image.tobytes()
    if mode == "png":
        return _encode_png(image)
    return _encode_jpeg(image, jpeg_quality=jpeg_quality)


def _png_size(data: bytes) -> tuple[int, int] | None:
    if not data or len(data) < 24:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width = int.from_bytes(data[16:20], "big", signed=False)
    height = int.from_bytes(data[20:24], "big", signed=False)
    if width <= 0 or height <= 0:
        return None
    return width, height


def _file_frames(
    paths: list[Path],
    *,
    loop: bool,
    max_frames: int,
    jpeg_quality: int,
    frame_format: str,
    timestamp_source: str,
) -> Iterator[Frame]:
    try:
        from PIL import Image
    except Exception:
        Image = None  # type: ignore[assignment]

    emitted = 0
    while True:
        for path in paths:
            if max_frames and emitted >= max_frames:
                return
            ts_utc = _frame_ts_utc(path, source=timestamp_source)
            if Image is None:
                if frame_format == "png" and path.suffix.lower() == ".png":
                    data = path.read_bytes()
                    size = _png_size(data)
                    if size is None:
                        continue
                    width, height = size
                    emitted += 1
                    yield Frame(
                        ts_utc=ts_utc,
                        data=data,
                        width=width,
                        height=height,
                        ts_monotonic=None,
                    )
                continue
            try:
                img = Image.open(path).convert("RGB")
            except Exception:
                continue
            data = _encode_frame(img, frame_format=frame_format, jpeg_quality=jpeg_quality)
            emitted += 1
            yield Frame(
                ts_utc=ts_utc,
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
    frame_format: str,
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
        data = _encode_frame(img, frame_format=frame_format, jpeg_quality=jpeg_quality)
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


def create_plugin(plugin_id: str, context: PluginContext) -> CaptureBasic:
    return CaptureBasic(plugin_id, context)


CaptureStub = CaptureBasic
