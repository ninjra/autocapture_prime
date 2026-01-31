"""Tray entrypoint for Autocapture NX (Windows)."""

from __future__ import annotations

import json
import os
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import default_config_paths


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


class UIServer:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._server = None
        self._thread: threading.Thread | None = None
        self._external = False

    def start(self) -> None:
        if _port_open(self._host, self._port):
            self._external = True
            return
        from autocapture.web.api import app
        import uvicorn

        config = uvicorn.Config(app, host=self._host, port=self._port, log_level="warning")
        server = uvicorn.Server(config)
        self._server = server
        self._thread = threading.Thread(target=server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            if _port_open(self._host, self._port):
                return
            time.sleep(0.1)
        raise RuntimeError("ui_server_start_failed")

    def stop(self) -> None:
        if self._external:
            return
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=2)


class UIWindow:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._window = None
        self._fallback = False

    def start(self) -> None:
        try:
            import webview
        except Exception as exc:
            _log(f"pywebview import failed: {exc}")
            self._fallback = True
            return

        try:
            self._window = webview.create_window(
                "Autocapture NX",
                url=f"{self._base_url}/#capture",
                width=1280,
                height=820,
            )
        except Exception as exc:
            _log(f"pywebview window create failed: {exc}")
            self._fallback = True
            return

        def _worker():
            while True:
                action = self._queue.get()
                if action is None:
                    break
                if not self._window:
                    _open_browser(f"{self._base_url}/#capture")
                    continue
                if action == "settings":
                    url = f"{self._base_url}/#settings"
                elif action == "plugins":
                    url = f"{self._base_url}/#plugins"
                else:
                    url = f"{self._base_url}/#capture"
                try:
                    self._window.load_url(url)
                except Exception:
                    _open_browser(url)
                try:
                    self._window.restore()
                except Exception:
                    pass

        try:
            webview.start(_worker, debug=False)
        except Exception as exc:
            _log(f"pywebview start failed: {exc}")
            self._fallback = True

    def show_settings(self) -> None:
        if self._fallback or self._window is None:
            _open_browser(f"{self._base_url}/#settings")
            return
        self._queue.put("settings")

    def show_plugins(self) -> None:
        if self._fallback or self._window is None:
            _open_browser(f"{self._base_url}/#plugins")
            return
        self._queue.put("plugins")

    def stop(self) -> None:
        self._queue.put(None)
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass


def _log(message: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[tray] {ts} {message}", flush=True)


def _open_browser(url: str) -> None:
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception as exc:
        _log(f"browser open failed: {exc}")


def _http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return None


def _validate_ui(base_url: str) -> None:
    root_status = _http_status(base_url)
    ui_status = _http_status(f"{base_url}/ui")
    if root_status and root_status >= 400:
        _log(f"ui root returned {root_status} for {base_url}")
    if ui_status and ui_status >= 400:
        _log(f"ui /ui returned {ui_status} for {base_url}/ui")


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("tray_supported_on_windows_only")

    config = load_config(default_config_paths(), safe_mode=False)
    web_cfg = config.get("web", {}) if isinstance(config, dict) else {}
    host = str(web_cfg.get("bind_host", "127.0.0.1"))
    port = int(web_cfg.get("bind_port", 8787))
    env_host = os.getenv("AUTOCAPTURE_TRAY_BIND_HOST")
    env_port = os.getenv("AUTOCAPTURE_TRAY_BIND_PORT")
    if env_host:
        host = env_host
    if env_port:
        try:
            port = int(env_port)
        except ValueError:
            _log(f"invalid AUTOCAPTURE_TRAY_BIND_PORT: {env_port}")
    base_url = f"http://{host}:{port}"

    server = UIServer(host, port)
    server.start()
    _validate_ui(base_url)

    if os.getenv("AUTOCAPTURE_TRAY_SMOKE") == "1":
        _log("smoke mode: ui server running")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        server.stop()
        return 0

    from autocapture_nx.windows.tray import TrayApp

    ui = UIWindow(base_url)
    tray: TrayApp | None = None
    stop_event = threading.Event()
    tooltip_thread: threading.Thread | None = None

    def open_settings() -> None:
        ui.show_settings()

    def open_plugins() -> None:
        ui.show_plugins()

    def quit_app() -> None:
        stop_event.set()
        if tooltip_thread is not None:
            tooltip_thread.join(timeout=1)
        if tray is not None:
            tray.stop()
        ui.stop()
        server.stop()

    def _fetch_status() -> dict[str, Any]:
        try:
            with urllib.request.urlopen(f"{base_url}/api/status", timeout=1.5) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _status_menu() -> list[tuple]:
        status = _fetch_status()
        capture_active = bool(status.get("capture_active"))
        processing = status.get("processing_state", {}) if isinstance(status, dict) else {}
        capture_status = status.get("capture_status", {}) if isinstance(status, dict) else {}
        disk = capture_status.get("disk", {}) if isinstance(capture_status, dict) else {}
        hard_halt = bool(disk.get("hard_halt")) if isinstance(disk, dict) else False
        capture_label = f"Capture: {'RUNNING' if capture_active else 'STOPPED'}"
        if hard_halt:
            capture_label = "Capture: HALTED (DISK LOW)"
        processing_label = "Processing: —"
        if isinstance(processing, dict) and processing.get("paused"):
            reason = processing.get("reason") or "active user"
            processing_label = f"Processing: PAUSED ({reason})"
        elif isinstance(processing, dict) and processing.get("mode"):
            processing_label = f"Processing: {processing.get('mode')}"
        disk_label = "Disk: —"
        if isinstance(disk, dict) and disk.get("level"):
            level = str(disk.get("level")).upper()
            free_gb = disk.get("free_gb")
            if hard_halt:
                disk_label = "Disk: CAPTURE HALTED (LOW)"
            elif isinstance(free_gb, int):
                disk_label = f"Disk: {level} · {free_gb} GB free"
            else:
                disk_label = f"Disk: {level}"
        return [
            (10, capture_label, None, False),
            (11, processing_label, None, False),
            (12, disk_label, None, False),
            (1, "Settings", open_settings),
            (2, "Plugin Manager", open_plugins),
            (3, "Quit", quit_app),
        ]

    def _tooltip_text(status: dict[str, Any]) -> str:
        capture_active = bool(status.get("capture_active"))
        capture_status = status.get("capture_status", {}) if isinstance(status, dict) else {}
        disk = capture_status.get("disk", {}) if isinstance(capture_status, dict) else {}
        if isinstance(disk, dict) and disk.get("hard_halt"):
            return "CAPTURE HALTED: DISK LOW"
        return f"Autocapture NX · Capture {'RUNNING' if capture_active else 'STOPPED'}"

    def _tooltip_loop() -> None:
        last_tip: str | None = None
        while not stop_event.is_set():
            status = _fetch_status()
            tip = _tooltip_text(status)
            if tray is not None and tip != last_tip:
                try:
                    tray.set_tooltip(tip)
                except Exception:
                    pass
                last_tip = tip
            stop_event.wait(5.0)

    menu = [
        (1, "Settings", open_settings),
        (2, "Plugin Manager", open_plugins),
        (3, "Quit", quit_app),
    ]

    tray = TrayApp("Autocapture NX", menu, default_id=1, menu_provider=_status_menu)
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()
    tooltip_thread = threading.Thread(target=_tooltip_loop, daemon=True)
    tooltip_thread.start()

    ui.start()
    if ui._fallback:
        _log("pywebview unavailable; using browser fallback")
        _open_browser(f"{base_url}/#capture")
        try:
            while tray_thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    server.stop()
    tray.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
