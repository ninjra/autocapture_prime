"""Native Windows tray helper using Win32 APIs."""

from __future__ import annotations

import atexit
import ctypes
import os
from ctypes import wintypes
from typing import Any, Callable, TypeAlias, cast


WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIM_SETVERSION = 0x00000004

NOTIFYICON_VERSION_4 = 4

TPM_LEFTALIGN = 0x0000
TPM_BOTTOMALIGN = 0x0020
TPM_RIGHTBUTTON = 0x0002

IDI_APPLICATION = 32512
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
PTR_LONG = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
PTR_ULONG = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
LRESULT = getattr(wintypes, "LRESULT", PTR_LONG)
WPARAM = getattr(wintypes, "WPARAM", PTR_ULONG)
LPARAM = getattr(wintypes, "LPARAM", PTR_LONG)
HICON: TypeAlias = wintypes.HICON
HCURSOR: TypeAlias = wintypes.HANDLE
HBRUSH: TypeAlias = wintypes.HANDLE
windll = cast(Any, getattr(ctypes, "windll", None))
WINFUNCTYPE = cast(Any, getattr(ctypes, "WINFUNCTYPE", None))


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("uVersion", wintypes.UINT),
    ]


class TrayApp:
    def __init__(
        self,
        title: str,
        menu: list[tuple[int, str, Callable[[], None]]],
        default_id: int,
        *,
        menu_provider: Callable[[], list[tuple]] | None = None,
    ) -> None:
        self._title = title
        self._menu_items = menu
        self._default_id = default_id
        self._callbacks: dict[int, Callable[[], None]] = {item_id: cb for item_id, _label, cb in menu}
        self._menu_provider = menu_provider
        self._instance = windll.kernel32.GetModuleHandleW(None)
        self._hwnd: wintypes.HWND | None = None
        self._notify_id = 1
        self._message_id = WM_USER + 1
        self._wndproc = None
        self._icon_handle: HICON | None = None

    def run(self) -> None:
        try:
            self._register_window_class()
            self._create_window()
            self._add_icon()
            atexit.register(self._remove_icon)
            self._message_loop()
        except Exception as exc:
            self._log(f"Tray run failed: {exc}")

    def stop(self) -> None:
        if self._hwnd:
            windll.user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        if self._icon_handle:
            try:
                windll.user32.DestroyIcon(self._icon_handle)
            except Exception:
                pass
            self._icon_handle = None

    def _log(self, message: str) -> None:
        print(f"[tray] {message}", flush=True)

    def _last_error(self) -> str:
        get_last_error = getattr(ctypes, "get_last_error", None)
        format_error = getattr(ctypes, "FormatError", None)
        err = get_last_error() if callable(get_last_error) else 0
        if callable(format_error):
            try:
                return format_error(err)
            except Exception:
                return str(err)
        return str(err)

    def _register_window_class(self) -> None:
        WNDPROC = WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

        def _def_window_proc(hwnd, msg, wparam, lparam):
            proc = windll.user32.DefWindowProcW
            proc.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
            proc.restype = LRESULT
            return proc(hwnd, msg, wparam, lparam)

        def _proc(hwnd, msg, wparam, lparam):
            if msg == self._message_id:
                if lparam == WM_LBUTTONUP:
                    self._invoke(self._default_id)
                elif lparam == WM_RBUTTONUP:
                    self._show_menu(hwnd)
                return 0
            if msg == WM_COMMAND:
                cmd_id = wparam & 0xFFFF
                self._invoke(cmd_id)
                return 0
            if msg == WM_DESTROY:
                windll.user32.PostQuitMessage(0)
                return 0
            return _def_window_proc(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(_proc)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", HICON),
                ("hCursor", HCURSOR),
                ("hbrBackground", HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = self._instance
        wc.hIcon = windll.user32.LoadIconW(None, IDI_APPLICATION)
        wc.hCursor = windll.user32.LoadCursorW(None, 32512)  # IDC_ARROW
        wc.hbrBackground = 0
        wc.lpszMenuName = None
        wc.lpszClassName = "AutocaptureNxTray"
        result = windll.user32.RegisterClassW(ctypes.byref(wc))
        if not result:
            self._log(f"RegisterClassW failed: {self._last_error()}")

    def _create_window(self) -> None:
        hwnd = windll.user32.CreateWindowExW(
            0,
            "AutocaptureNxTray",
            self._title,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self._instance,
            None,
        )
        self._hwnd = hwnd
        if not hwnd:
            self._log(f"CreateWindowExW failed: {self._last_error()}")

    def _add_icon(self) -> None:
        if not self._hwnd:
            return
        icon_path = os.getenv("AUTOCAPTURE_TRAY_ICON", "").strip()
        icon = None
        if icon_path:
            icon = windll.user32.LoadImageW(
                None,
                icon_path,
                1,
                0,
                0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if not icon:
                self._log(f"LoadImageW failed for icon {icon_path}: {self._last_error()}")
        if not icon:
            icon = windll.user32.LoadIconW(None, IDI_APPLICATION)
        self._icon_handle = icon
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = self._notify_id
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self._message_id
        nid.hIcon = icon
        nid.szTip = self._title
        if not windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            self._log(f"Shell_NotifyIconW(NIM_ADD) failed: {self._last_error()}")
            return
        try:
            nid.uVersion = NOTIFYICON_VERSION_4  # type: ignore[attr-defined]
            windll.shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
        except Exception:
            pass

    def _remove_icon(self) -> None:
        if not self._hwnd:
            return
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = self._notify_id
        windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    def _message_loop(self) -> None:
        msg = wintypes.MSG()
        while windll.user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            windll.user32.TranslateMessage(ctypes.byref(msg))
            windll.user32.DispatchMessageW(ctypes.byref(msg))

    def _show_menu(self, hwnd: wintypes.HWND) -> None:
        menu = windll.user32.CreatePopupMenu()
        items = self._menu_items
        if self._menu_provider is not None:
            try:
                items = self._menu_provider()
            except Exception:
                items = self._menu_items
        self._callbacks = {}
        for item in items:
            if len(item) == 4:
                item_id, label, callback, enabled = item
            else:
                item_id, label, callback = item
                enabled = True
            flags = 0
            if not enabled:
                flags = 0x0001
            windll.user32.AppendMenuW(menu, flags, item_id, label)
            if callback is not None:
                self._callbacks[item_id] = callback
        windll.user32.SetMenuDefaultItem(menu, self._default_id, False)
        point = wintypes.POINT()
        windll.user32.GetCursorPos(ctypes.byref(point))
        windll.user32.SetForegroundWindow(hwnd)
        windll.user32.TrackPopupMenu(
            menu,
            TPM_LEFTALIGN | TPM_BOTTOMALIGN | TPM_RIGHTBUTTON,
            point.x,
            point.y,
            0,
            hwnd,
            None,
        )
        try:
            windll.user32.PostMessageW(hwnd, 0, 0, 0)
        except Exception:
            pass
        windll.user32.DestroyMenu(menu)

    def _invoke(self, item_id: int) -> None:
        callback = self._callbacks.get(item_id)
        if callback:
            callback()
