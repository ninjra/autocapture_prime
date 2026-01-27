"""Subprocess plugin host implementation."""

from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, IO

from autocapture_nx.kernel.errors import PermissionError, PluginError
from autocapture_nx.windows.win_sandbox import assign_job_object


def _encode(obj: Any) -> Any:
    if isinstance(obj, (bytes, bytearray)):
        import base64

        return {"__bytes__": base64.b64encode(obj).decode("ascii")}
    if isinstance(obj, list):
        return [_encode(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
    return obj


def _decode(obj: Any) -> Any:
    if isinstance(obj, dict) and "__bytes__" in obj:
        import base64

        return base64.b64decode(obj["__bytes__"])
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _decode(v) for k, v in obj.items()}
    return obj


def _hosting_cfg(config: dict[str, Any]) -> dict[str, Any]:
    plugins = config.get("plugins", {}) if isinstance(config, dict) else {}
    hosting = plugins.get("hosting", {})
    return hosting if isinstance(hosting, dict) else {}


def _cache_dir(hosting: dict[str, Any], config: dict[str, Any]) -> Path:
    raw = hosting.get("cache_dir")
    if raw:
        return Path(str(raw))
    data_dir = config.get("storage", {}).get("data_dir", "data")
    return Path(str(data_dir)) / "cache" / "plugins"


def _build_env(hosting: dict[str, Any], config: dict[str, Any]) -> dict[str, str] | None:
    if not bool(hosting.get("sanitize_env", True)):
        return None
    env = os.environ.copy()
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        env.pop(key, None)

    cache_dir = _cache_dir(hosting, config)
    tmp_dir = cache_dir / "tmp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(tmp_dir)
    env["TMP"] = str(tmp_dir)
    env["TEMP"] = str(tmp_dir)
    env["XDG_CACHE_HOME"] = str(cache_dir)
    env["PIP_CACHE_DIR"] = str(cache_dir / "pip")
    env["AUTOCAPTURE_CACHE_DIR"] = str(cache_dir)
    return env


@dataclass
class RemoteCapability:
    host: "PluginProcess"
    name: str
    methods: list[str]

    def __getattr__(self, item: str):
        if item not in self.methods:
            raise AttributeError(item)

        def _call(*args, **kwargs):
            return self.host.call(self.name, item, args, kwargs)

        return _call


class PluginProcess:
    def __init__(self, plugin_path: Path, callable_name: str, plugin_id: str, network_allowed: bool, config: dict[str, Any]) -> None:
        hosting = _hosting_cfg(config)
        self._rpc_timeout_s = float(hosting.get("rpc_timeout_s", 10))
        self._rpc_max_message_bytes = int(hosting.get("rpc_max_message_bytes", 2_000_000))
        self._write_lock = threading.Lock()
        self._response_lock = threading.Lock()
        self._responses: dict[int, queue.Queue] = {}
        self._reader_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._reader_error: str | None = None

        self._proc: subprocess.Popen[str] | None = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "autocapture_nx.plugin_system.host_runner",
                str(plugin_path),
                callable_name,
                plugin_id,
                "true" if network_allowed else "false",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=_build_env(hosting, config),
        )
        if self._proc.stdin is None or self._proc.stdout is None:
            raise PluginError("Failed to start plugin host")
        assign_job_object(self._proc.pid)
        self._stdin: IO[str] = self._proc.stdin
        self._stdout: IO[str] = self._proc.stdout
        self._req_id = 0
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        self._send_payload(config)

    def _send_payload(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload)
        size = len(text.encode("utf-8"))
        if size > self._rpc_max_message_bytes:
            raise PluginError(f"payload too large for plugin host ({size} bytes)")
        with self._write_lock:
            self._stdin.write(text + "\n")
            self._stdin.flush()

    def _set_reader_error(self, message: str) -> None:
        if self._reader_error:
            return
        self._reader_error = message
        with self._response_lock:
            pending = list(self._responses.items())
            self._responses.clear()
        for _req_id, resp_q in pending:
            try:
                resp_q.put_nowait({"id": _req_id, "ok": False, "error": message})
            except Exception:
                pass

    def _reader_loop(self) -> None:
        while not self._reader_stop.is_set():
            line = self._stdout.readline()
            if not line:
                self._set_reader_error("Plugin host closed")
                return
            size = len(line.encode("utf-8"))
            if size > self._rpc_max_message_bytes:
                self._set_reader_error(f"plugin host response too large ({size} bytes)")
                return
            try:
                response = json.loads(line)
            except Exception as exc:
                self._set_reader_error(f"invalid plugin host response: {exc}")
                return
            req_id = response.get("id")
            if req_id is None:
                continue
            with self._response_lock:
                resp_q = self._responses.get(int(req_id))
            if resp_q is None:
                continue
            try:
                resp_q.put_nowait(response)
            except Exception:
                pass

    def close(self) -> None:
        proc = getattr(self, "_proc", None)
        if proc is None:
            return
        try:
            self._reader_stop.set()
            self._set_reader_error("Plugin host shutting down")
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        pass
        finally:
            if self._reader_thread and self._reader_thread.is_alive():
                try:
                    self._reader_thread.join(timeout=1)
                except Exception:
                    pass
                self._reader_thread = None
            for stream in (getattr(self, "_stdin", None), getattr(self, "_stdout", None)):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            self._proc = None

    def _request(self, payload: dict[str, Any]) -> Any:
        if self._reader_error:
            raise PluginError(self._reader_error)
        self._req_id += 1
        req_id = self._req_id
        payload["id"] = req_id
        resp_q: queue.Queue = queue.Queue(maxsize=1)
        with self._response_lock:
            self._responses[req_id] = resp_q
        self._send_payload(payload)
        try:
            response = resp_q.get(timeout=max(0.1, float(self._rpc_timeout_s)))
        except queue.Empty as exc:
            self.close()
            raise PluginError(f"Plugin host request timed out after {self._rpc_timeout_s:.2f}s") from exc
        finally:
            with self._response_lock:
                self._responses.pop(req_id, None)
        if not response.get("ok"):
            raise PluginError(response.get("error", "unknown error"))
        return response.get("result")

    def capabilities(self) -> dict[str, list[str]]:
        return self._request({"method": "capabilities"})

    def call(self, capability: str, function: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        payload = {
            "method": "call",
            "capability": capability,
            "function": function,
            "args": _encode(args),
            "kwargs": _encode(kwargs),
        }
        try:
            return _decode(self._request(payload))
        except PluginError as exc:
            if "Network access is denied" in str(exc):
                raise PermissionError(str(exc)) from exc
            raise


class SubprocessPlugin:
    def __init__(self, plugin_path: Path, callable_name: str, plugin_id: str, network_allowed: bool, config: dict[str, Any]):
        self._host: PluginProcess | None = PluginProcess(plugin_path, callable_name, plugin_id, network_allowed, config)
        atexit.register(self.close)
        self._caps: dict[str, RemoteCapability] = {}
        for name, methods in self._host.capabilities().items():
            self._caps[name] = RemoteCapability(self._host, name, methods)

    def capabilities(self) -> dict[str, Any]:
        return self._caps

    def close(self) -> None:
        if getattr(self, "_host", None) is None:
            return
        try:
            assert self._host is not None
            self._host.close()
        finally:
            self._host = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
