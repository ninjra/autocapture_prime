"""Windows capture helpers using optional dependencies."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class Frame:
    ts_utc: str
    data: bytes
    width: int
    height: int


def _iso_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def iter_screenshots(fps: int) -> Iterator[Frame]:
    if os.name != "nt":
        raise RuntimeError("Screen capture supported on Windows only")
    try:
        import mss
        from PIL import Image
    except Exception as exc:
        raise RuntimeError(f"Missing capture dependencies: {exc}")

    interval = 1.0 / max(fps, 1)
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        while True:
            start = time.time()
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
            buf = bytearray()
            from io import BytesIO

            bio = BytesIO()
            img.save(bio, format="JPEG", quality=90)
            data = bio.getvalue()
            yield Frame(ts_utc=_iso_utc(), data=data, width=raw.width, height=raw.height)
            elapsed = time.time() - start
            if elapsed < interval:
                time.sleep(interval - elapsed)
