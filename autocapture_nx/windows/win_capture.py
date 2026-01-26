"""Windows capture helpers using optional dependencies."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator


@dataclass
class Frame:
    ts_utc: str
    data: bytes
    width: int
    height: int


def _iso_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def iter_screenshots(
    fps: int | Callable[[], int],
    *,
    frame_source: Iterator[Frame] | None = None,
    now_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Iterator[Frame]:
    if callable(fps):
        fps_provider = fps
    else:
        fps_provider = lambda: fps

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
                monitor = sct.monitors[0]
                while True:
                    raw = sct.grab(monitor)
                    img = Image.frombytes("RGB", raw.size, raw.rgb)
                    from io import BytesIO

                    bio = BytesIO()
                    img.save(bio, format="JPEG", quality=90)
                    data = bio.getvalue()
                    yield Frame(ts_utc=_iso_utc(), data=data, width=raw.width, height=raw.height)

        frame_source = _frames()

    for frame in frame_source:
        start = now_fn()
        yield frame
        interval = 1.0 / max(int(fps_provider()), 1)
        elapsed = now_fn() - start
        if elapsed < interval:
            sleep_fn(interval - elapsed)
