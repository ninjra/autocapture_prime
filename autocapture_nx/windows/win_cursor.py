"""Windows cursor helpers."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass


@dataclass
class CursorInfo:
    x: int
    y: int
    visible: bool
    handle: int


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", POINT),
    ]


def current_cursor() -> CursorInfo | None:
    if os.name != "nt":
        return None
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)
    if not user32.GetCursorInfo(ctypes.byref(info)):
        return None
    visible = bool(info.flags & 0x00000001)
    return CursorInfo(
        x=int(info.ptScreenPos.x),
        y=int(info.ptScreenPos.y),
        visible=visible,
        handle=int(info.hCursor or 0),
    )
