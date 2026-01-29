"""Tray entrypoint for Autocapture NX (Windows)."""

from __future__ import annotations

import os
import queue
import socket
import threading
import time

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
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
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
        self._base_url = base_url
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
                url=f"{self._base_url}/#settings",
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
                    continue
                if action == "settings":
                    url = f"{self._base_url}/#settings"
                elif action == "plugins":
                    url = f"{self._base_url}/#plugins"
                else:
                    url = f"{self._base_url}/#settings"
                try:
                    self._window.load_url(url)
                except Exception:
                    pass
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
        if self._fallback:
            _open_browser(f"{self._base_url}/#settings")
            return
        self._queue.put("settings")

    def show_plugins(self) -> None:
        if self._fallback:
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
    base_url = f"http://{host}:{port}/ui"

    server = UIServer(host, port)
    server.start()

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

    def open_settings() -> None:
        ui.show_settings()

    def open_plugins() -> None:
        ui.show_plugins()

    def quit_app() -> None:
        if tray is not None:
            tray.stop()
        ui.stop()
        server.stop()

    menu = [
        (1, "Settings", open_settings),
        (2, "Plugin Manager", open_plugins),
        (3, "Quit", quit_app),
    ]

    tray = TrayApp("Autocapture NX", menu, default_id=1)
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    ui.start()
    if ui._fallback:
        _log("pywebview unavailable; using browser fallback")
        _open_browser(f"{base_url}/#settings")
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
