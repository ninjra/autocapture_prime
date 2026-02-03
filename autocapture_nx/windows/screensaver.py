"""Windows screensaver state helpers."""

from __future__ import annotations

import ctypes
import os


SPI_GETSCREENSAVERRUNNING = 0x0072


def screensaver_running() -> bool | None:
    """Return True if screensaver is running, False if not, None if unsupported."""
    if os.name != "nt":
        return None
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    except Exception:
        return None
    try:
        running = ctypes.c_uint(0)
        ok = user32.SystemParametersInfoW(
            SPI_GETSCREENSAVERRUNNING,
            0,
            ctypes.byref(running),
            0,
        )
        if not ok:
            return None
        return bool(running.value)
    except Exception:
        return None
