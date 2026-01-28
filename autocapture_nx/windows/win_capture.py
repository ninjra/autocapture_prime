"""Windows capture helpers using optional dependencies."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Iterator


@dataclass
class Frame:
    ts_utc: str
    data: bytes
    width: int
    height: int
    ts_monotonic: float | None = None


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
    monitor_index: int = 0,
    resolution: str | None = None,
) -> Iterator[Frame]:
    if callable(fps):
        fps_provider = fps
    else:
        def fps_provider() -> int:
            return fps

    if frame_source is None:
        if os.name != "nt":
            raise RuntimeError("Screen capture supported on Windows only")
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
                target_size = _parse_resolution(resolution, monitor.get("width"), monitor.get("height"))
                while True:
                    raw = sct.grab(monitor)
                    img = Image.frombytes("RGB", raw.size, raw.rgb)
                    if target_size and (img.width, img.height) != target_size:
                        img = img.resize(target_size)
                    from io import BytesIO

                    bio = BytesIO()
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
