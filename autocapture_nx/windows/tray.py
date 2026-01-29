"""Native Windows tray helper using Win32 APIs."""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
from typing import Callable


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

TPM_LEFTALIGN = 0x0000
TPM_BOTTOMALIGN = 0x0020
TPM_RIGHTBUTTON = 0x0002

IDI_APPLICATION = 32512
PTR_LONG = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
PTR_ULONG = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
LRESULT = getattr(wintypes, "LRESULT", PTR_LONG)
WPARAM = getattr(wintypes, "WPARAM", PTR_ULONG)
LPARAM = getattr(wintypes, "LPARAM", PTR_LONG)
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
    ]


class TrayApp:
    def __init__(self, title: str, menu: list[tuple[int, str, Callable[[], None]]], default_id: int) -> None:
        self._title = title
        self._menu_items = menu
        self._default_id = default_id
        self._callbacks: dict[int, Callable[[], None]] = {item_id: cb for item_id, _label, cb in menu}
        self._instance = ctypes.windll.kernel32.GetModuleHandleW(None)
        self._hwnd: wintypes.HWND | None = None
        self._notify_id = 1
        self._message_id = WM_USER + 1
        self._wndproc = None

    def run(self) -> None:
        self._register_window_class()
        self._create_window()
        self._add_icon()
        atexit.register(self._remove_icon)
        self._message_loop()

    def stop(self) -> None:
        if self._hwnd:
            ctypes.windll.user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    def _register_window_class(self) -> None:
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

        def _def_window_proc(hwnd, msg, wparam, lparam):
            proc = ctypes.windll.user32.DefWindowProcW
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
                ctypes.windll.user32.PostQuitMessage(0)
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
        wc.hIcon = ctypes.windll.user32.LoadIconW(None, IDI_APPLICATION)
        wc.hCursor = ctypes.windll.user32.LoadCursorW(None, 32512)  # IDC_ARROW
        wc.hbrBackground = 0
        wc.lpszMenuName = None
        wc.lpszClassName = "AutocaptureNxTray"
        ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))

    def _create_window(self) -> None:
        hwnd = ctypes.windll.user32.CreateWindowExW(
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

    def _add_icon(self) -> None:
        if not self._hwnd:
            return
        icon = ctypes.windll.user32.LoadIconW(None, IDI_APPLICATION)
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = self._notify_id
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self._message_id
        nid.hIcon = icon
        nid.szTip = self._title
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _remove_icon(self) -> None:
        if not self._hwnd:
            return
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = self._notify_id
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    def _message_loop(self) -> None:
        msg = wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

    def _show_menu(self, hwnd: wintypes.HWND) -> None:
        menu = ctypes.windll.user32.CreatePopupMenu()
        for item_id, label, _cb in self._menu_items:
            ctypes.windll.user32.AppendMenuW(menu, 0, item_id, label)
        ctypes.windll.user32.SetMenuDefaultItem(menu, self._default_id, False)
        point = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        ctypes.windll.user32.TrackPopupMenu(
            menu,
            TPM_LEFTALIGN | TPM_BOTTOMALIGN | TPM_RIGHTBUTTON,
            point.x,
            point.y,
            0,
            hwnd,
            None,
        )
        ctypes.windll.user32.DestroyMenu(menu)

    def _invoke(self, item_id: int) -> None:
        callback = self._callbacks.get(item_id)
        if callback:
            callback()
