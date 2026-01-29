"""Windows cursor helpers."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


@dataclass
class CursorInfo:
    x: int
    y: int
    visible: bool
    handle: int


@dataclass
class CursorShape:
    image: "Image.Image"
    hotspot_x: int
    hotspot_y: int
    width: int
    height: int


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", POINT),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", ctypes.c_bool),
        ("xHotspot", ctypes.c_ulong),
        ("yHotspot", ctypes.c_ulong),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", ctypes.c_long),
        ("bmWidth", ctypes.c_long),
        ("bmHeight", ctypes.c_long),
        ("bmWidthBytes", ctypes.c_long),
        ("bmPlanes", ctypes.c_ushort),
        ("bmBitsPixel", ctypes.c_ushort),
        ("bmBits", ctypes.c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_ulong),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_ulong),
        ("biSizeImage", ctypes.c_ulong),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_ulong),
        ("biClrImportant", ctypes.c_ulong),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", ctypes.c_ubyte),
        ("rgbGreen", ctypes.c_ubyte),
        ("rgbRed", ctypes.c_ubyte),
        ("rgbReserved", ctypes.c_ubyte),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", RGBQUAD * 1),
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


def cursor_shape(handle: int) -> CursorShape | None:
    if os.name != "nt":
        return None
    if not handle:
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
    iconinfo = ICONINFO()
    if not user32.GetIconInfo(ctypes.c_void_p(handle), ctypes.byref(iconinfo)):
        return None
    try:
        hbm = iconinfo.hbmColor or iconinfo.hbmMask
        if not hbm:
            return None
        bmp = BITMAP()
        if not gdi32.GetObjectW(ctypes.c_void_p(hbm), ctypes.sizeof(BITMAP), ctypes.byref(bmp)):
            return None
        width = int(bmp.bmWidth)
        height = int(bmp.bmHeight if iconinfo.hbmColor else bmp.bmHeight // 2)
        if width <= 0 or height <= 0:
            return None

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        dib_ptr = ctypes.c_void_p()
        hdc = user32.GetDC(None)
        memdc = gdi32.CreateCompatibleDC(hdc)
        if not memdc:
            user32.ReleaseDC(None, hdc)
            return None
        dib = gdi32.CreateDIBSection(memdc, ctypes.byref(bmi), 0, ctypes.byref(dib_ptr), None, 0)
        if not dib:
            gdi32.DeleteDC(memdc)
            user32.ReleaseDC(None, hdc)
            return None
        old = gdi32.SelectObject(memdc, dib)
        user32.DrawIconEx(memdc, 0, 0, ctypes.c_void_p(handle), width, height, 0, None, 0x0003)
        size = width * height * 4
        raw = ctypes.string_at(dib_ptr, size)
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(dib)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(None, hdc)
        img = Image.frombuffer("RGBA", (width, height), raw, "raw", "BGRA", 0, 1)
        return CursorShape(
            image=img,
            hotspot_x=int(iconinfo.xHotspot),
            hotspot_y=int(iconinfo.yHotspot),
            width=width,
            height=height,
        )
    finally:
        if iconinfo.hbmColor:
            gdi32.DeleteObject(ctypes.c_void_p(iconinfo.hbmColor))
        if iconinfo.hbmMask:
            gdi32.DeleteObject(ctypes.c_void_p(iconinfo.hbmMask))
