"""Windows capture helpers using optional dependencies."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterator

if TYPE_CHECKING:
    from autocapture_nx.windows.win_cursor import CursorInfo, CursorShape


@dataclass
class Frame:
    ts_utc: str
    data: bytes
    width: int
    height: int
    ts_monotonic: float | None = None


@dataclass(frozen=True)
class CaptureBackend:
    name: str
    frames: Iterator[Frame]

    def capture_once(self) -> Frame:
        return next(self.frames)


def _iso_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def iter_screenshots(
    fps: int | Callable[[], int],
    *,
    frame_source: Iterator[Frame] | None = None,
    now_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    jpeg_quality: int | Callable[[], int] = 90,
    frame_format: str = "jpeg",
    monitor_index: int = 0,
    resolution: str | None = None,
    include_cursor: bool = False,
    include_cursor_shape: bool = True,
) -> Iterator[Frame]:
    if callable(fps):
        fps_provider = fps
    else:
        def fps_provider() -> int:
            return fps

    frame_mode = str(frame_format or "jpeg").strip().lower()
    if frame_mode not in {"jpeg", "png", "rgb"}:
        frame_mode = "jpeg"

    if frame_source is None:
        if os.name != "nt":
            frame_source = iter(())
        else:
            try:
                import mss
                from PIL import Image
            except Exception as exc:
                raise RuntimeError(f"Missing capture dependencies: {exc}")

            def _frames() -> Iterator[Frame]:
                with mss.mss() as sct:
                    monitors = sct.monitors
                    idx = int(monitor_index)
                    if idx < 0 or idx >= len(monitors):
                        idx = 0
                    monitor = monitors[idx]
                    mon_left = int(monitor.get("left", 0))
                    mon_top = int(monitor.get("top", 0))
                    target_size = _parse_resolution(resolution, monitor.get("width"), monitor.get("height"))
                    cursor_handle = None
                    cursor_cached = None
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

                    def _cursor_shape_cached(handle: int):
                        nonlocal cursor_handle, cursor_cached
                        if not handle or cursor_shape is None:
                            return None
                        if cursor_handle != handle or cursor_cached is None:
                            cursor_handle = handle
                            cursor_cached = cursor_shape(handle)
                        return cursor_cached

                    while True:
                        raw = sct.grab(monitor)
                        img = Image.frombytes("RGB", raw.size, raw.rgb)
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
                        yield Frame(
                            ts_utc=_iso_utc(),
                            data=data,
                            width=img.width,
                            height=img.height,
                            ts_monotonic=time.monotonic(),
                        )

            frame_source = _frames()

    for frame in frame_source:
        start = now_fn()
        if frame.ts_monotonic is None:
            frame = Frame(
                ts_utc=frame.ts_utc,
                data=frame.data,
                width=frame.width,
                height=frame.height,
                ts_monotonic=start,
            )
        yield frame
        interval = 1.0 / max(int(fps_provider()), 1)
        elapsed = now_fn() - start
        if elapsed < interval:
            sleep_fn(interval - elapsed)


def create_capture_backend(
    backend: str,
    *,
    fps: int | Callable[[], int] = 1,
    frame_source: Iterator[Frame] | None = None,
    jpeg_quality: int | Callable[[], int] = 90,
    frame_format: str = "jpeg",
    monitor_index: int = 0,
    resolution: str | None = None,
    include_cursor: bool = False,
    include_cursor_shape: bool = True,
) -> CaptureBackend:
    name = str(backend or "mss").strip().lower()
    if name in {"mss", "mss_jpeg"}:
        frames = iter_screenshots(
            fps,
            frame_source=frame_source,
            jpeg_quality=jpeg_quality,
            frame_format=frame_format,
            monitor_index=monitor_index,
            resolution=resolution,
            include_cursor=include_cursor,
            include_cursor_shape=include_cursor_shape,
        )
        return CaptureBackend(name="mss_jpeg", frames=frames)
    if name in {"dd_nvenc", "dxcam"}:
        try:
            from autocapture_nx.capture.pipeline import _dxcam_frames
        except Exception as exc:
            raise RuntimeError(f"DXCAM backend unavailable: {exc}")
        frames = _dxcam_frames(
            fps if callable(fps) else (lambda: int(fps)),
            jpeg_quality=jpeg_quality,
            frame_format=frame_format,
            monitor_index=monitor_index,
            resolution=resolution,
            include_cursor=include_cursor,
            include_cursor_shape=include_cursor_shape,
        )
        return CaptureBackend(name="dd_nvenc", frames=frames)
    raise RuntimeError(f"Unknown capture backend: {backend}")


def capture_once(
    backend: str,
    *,
    fps: int | Callable[[], int] = 1,
    frame_source: Iterator[Frame] | None = None,
    jpeg_quality: int | Callable[[], int] = 90,
    frame_format: str = "jpeg",
    monitor_index: int = 0,
    resolution: str | None = None,
    include_cursor: bool = False,
    include_cursor_shape: bool = True,
) -> Frame:
    backend_obj = create_capture_backend(
        backend,
        fps=fps,
        frame_source=frame_source,
        jpeg_quality=jpeg_quality,
        frame_format=frame_format,
        monitor_index=monitor_index,
        resolution=resolution,
        include_cursor=include_cursor,
        include_cursor_shape=include_cursor_shape,
    )
    return backend_obj.capture_once()


def _parse_resolution(value: str | None, width: int | None, height: int | None) -> tuple[int, int] | None:
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


def list_monitors() -> list[dict[str, int | bool]] | None:
    if os.name != "nt":
        return None
    try:
        import mss
    except Exception:
        return None
    try:
        with mss.mss() as sct:
            monitors = sct.monitors
    except Exception:
        return None
    layout: list[dict[str, int | bool]] = []
    for idx, monitor in enumerate(monitors):
        layout.append(
            {
                "index": int(idx),
                "left": int(monitor.get("left", 0)),
                "top": int(monitor.get("top", 0)),
                "width": int(monitor.get("width", 0)),
                "height": int(monitor.get("height", 0)),
                "combined": bool(idx == 0),
            }
        )
    return layout
