"""Subprocess plugin host implementation."""

from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, IO

from autocapture_nx.kernel.errors import PermissionError, PluginError, PluginTimeoutError
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
    env["HF_HOME"] = str(cache_dir / "hf")
    env["HF_DATASETS_CACHE"] = str(cache_dir / "hf" / "datasets")
    env["TRANSFORMERS_CACHE"] = str(cache_dir / "hf" / "transformers")
    env["TORCH_HOME"] = str(cache_dir / "torch")
    offline = bool(hosting.get("offline_env", True))
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["HF_DATASETS_OFFLINE"] = "1"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        env["WANDB_DISABLED"] = "true"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _resolve_python_exe() -> str:
    override = os.getenv("AUTOCAPTURE_PYTHON_EXE", "").strip()
    if override:
        override = override.strip('"')
        try:
            if Path(override).exists():
                os.environ["AUTOCAPTURE_PYTHON_EXE"] = override
                return override
        except Exception:
            pass
    try:
        if os.name == "nt":
            venv_candidate = Path(sys.prefix) / "Scripts" / "python.exe"
            if venv_candidate.exists():
                os.environ["AUTOCAPTURE_PYTHON_EXE"] = str(venv_candidate)
                return str(venv_candidate)
        else:
            venv_candidate = Path(sys.prefix) / "bin" / "python"
            if venv_candidate.exists():
                os.environ["AUTOCAPTURE_PYTHON_EXE"] = str(venv_candidate)
                return str(venv_candidate)
    except Exception:
        pass
    os.environ.setdefault("AUTOCAPTURE_PYTHON_EXE", sys.executable)
    return sys.executable


def _adjust_job_limits_for_venv(python_exe: str, limits: dict[str, Any] | None) -> dict[str, Any] | None:
    if os.name != "nt":
        return limits
    if not limits:
        return limits
    try:
        exe_path = Path(python_exe)
        cfg = exe_path.parents[1] / "pyvenv.cfg"
        if not cfg.exists():
            return limits
    except Exception:
        return limits
    adjusted = dict(limits)
    max_proc = int(adjusted.get("max_processes", 1) or 0)
    if max_proc > 0 and max_proc < 2:
        adjusted["max_processes"] = 2
    return adjusted


@dataclass
class RemoteCapability:
    host: "SubprocessPlugin"
    name: str
    methods: list[str]

    def __getattr__(self, item: str):
        if item not in self.methods:
            raise AttributeError(item)

        def _call(*args, **kwargs):
            return self.host._call(self.name, item, list(args), dict(kwargs))

        return _call

    def update_methods(self, methods: list[str]) -> None:
        self.methods = list(methods)


class PluginProcess:
    def __init__(
        self,
        plugin_path: Path,
        callable_name: str,
        plugin_id: str,
        network_allowed: bool,
        host_config: dict[str, Any],
        plugin_config: dict[str, Any],
        *,
        capabilities: Any,
        allowed_capabilities: set[str] | None,
        filesystem_policy: dict[str, Any] | None = None,
    ) -> None:
        hosting = _hosting_cfg(host_config)
        self._rpc_timeout_s = float(hosting.get("rpc_timeout_s", 10))
        self._rpc_max_message_bytes = int(hosting.get("rpc_max_message_bytes", 2_000_000))
        self._write_lock = threading.Lock()
        self._response_lock = threading.Lock()
        self._responses: dict[int, queue.Queue] = {}
        self._reader_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._reader_error: str | None = None
        self._capabilities = capabilities
        self._allowed_capabilities = set(allowed_capabilities) if allowed_capabilities else None
        self._plugin_id = plugin_id
        self._filesystem_policy = filesystem_policy

        python_exe = _resolve_python_exe()
        self._proc: subprocess.Popen[str] | None = subprocess.Popen(
            [
                python_exe,
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
            env=_build_env(hosting, host_config),
        )
        if self._proc.stdin is None or self._proc.stdout is None:
            raise PluginError("Failed to start plugin host")
        limits = _adjust_job_limits_for_venv(python_exe, hosting.get("job_limits", {}))
        assign_job_object(self._proc.pid, limits=limits)
        self._stdin: IO[str] = self._proc.stdin
        self._stdout: IO[str] = self._proc.stdout
        self._req_id = 0
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        init_payload: dict[str, Any] = {"config": plugin_config, "host_config": host_config}
        init_payload["allowed_capabilities"] = (
            None if self._allowed_capabilities is None else sorted(self._allowed_capabilities)
        )
        init_payload["filesystem_policy"] = self._filesystem_policy
        self._send_payload(init_payload)

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
            if response.get("method") == "cap_call":
                cap_response = self._handle_cap_call(response)
                try:
                    self._send_payload(cap_response)
                except Exception as exc:
                    self._set_reader_error(str(exc))
                    return
                continue
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

    def _cap_allowed(self, capability: str) -> bool:
        allowed = self._allowed_capabilities
        if allowed is None:
            return True
        return capability in allowed

    def _handle_cap_call(self, request: dict[str, Any]) -> dict[str, Any]:
        req_id = int(request.get("id", 0))
        capability = str(request.get("capability", ""))
        function = str(request.get("function", ""))
        if not capability:
            return {"id": req_id, "ok": False, "error": "missing capability", "response_to": "cap_call"}
        if not self._cap_allowed(capability):
            return {
                "id": req_id,
                "ok": False,
                "error": f"capability not allowed: {capability}",
                "response_to": "cap_call",
            }
        caps = self._capabilities
        if caps is None:
            return {
                "id": req_id,
                "ok": False,
                "error": f"capability registry unavailable: {capability}",
                "response_to": "cap_call",
            }
        try:
            cap_obj = caps.get(capability)
        except Exception as exc:
            return {
                "id": req_id,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "response_to": "cap_call",
            }
        try:
            args = _decode(request.get("args", []))
            kwargs = _decode(request.get("kwargs", {}))
            if function:
                target = getattr(cap_obj, function)
                if not callable(target):
                    raise PluginError(f"capability method not callable: {capability}.{function}")
                result = target(*args, **kwargs)
            else:
                if callable(cap_obj):
                    result = cap_obj(*args, **kwargs)
                else:
                    result = cap_obj
            return {"id": req_id, "ok": True, "result": _encode(result), "response_to": "cap_call"}
        except Exception as exc:
            return {
                "id": req_id,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "response_to": "cap_call",
            }

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
            raise PluginTimeoutError(f"Plugin host request timed out after {self._rpc_timeout_s:.2f}s") from exc
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
    def __init__(
        self,
        plugin_path: Path,
        callable_name: str,
        plugin_id: str,
        network_allowed: bool,
        config: dict[str, Any],
        *,
        plugin_config: dict[str, Any] | None = None,
        capabilities: Any,
        allowed_capabilities: set[str] | None,
        filesystem_policy: dict[str, Any] | None = None,
    ):
        self._plugin_path = plugin_path
        self._callable_name = callable_name
        self._plugin_id = plugin_id
        self._network_allowed = network_allowed
        self._config = config
        self._plugin_config = plugin_config if isinstance(plugin_config, dict) else config
        self._capabilities = capabilities
        self._allowed_capabilities = allowed_capabilities
        self._filesystem_policy = filesystem_policy
        hosting = _hosting_cfg(config)
        self._timeout_limit = int(hosting.get("rpc_timeout_limit", 3))
        self._timeout_window_s = float(hosting.get("rpc_timeout_window_s", 60))
        self._restart_backoff_s = float(hosting.get("rpc_watchdog_backoff_s", 0.2))
        self._restart_max = int(hosting.get("rpc_watchdog_restart_max", 3))
        self._timeout_events: list[float] = []
        self._restart_count = 0
        self._host: PluginProcess | None = None
        self._caps: dict[str, RemoteCapability] = {}
        self._cap_methods: dict[str, set[str]] = {}
        self._start_host()
        atexit.register(self.close)

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

    def _start_host(self) -> None:
        self._host = PluginProcess(
            self._plugin_path,
            self._callable_name,
            self._plugin_id,
            self._network_allowed,
            self._config,
            self._plugin_config,
            capabilities=self._capabilities,
            allowed_capabilities=self._allowed_capabilities,
            filesystem_policy=self._filesystem_policy,
        )
        self._refresh_caps()

    def _refresh_caps(self) -> None:
        if self._host is None:
            return
        caps = self._host.capabilities()
        self._cap_methods = {name: set(methods) for name, methods in caps.items()}
        for name, methods in self._cap_methods.items():
            if name not in self._caps:
                self._caps[name] = RemoteCapability(self, name, sorted(methods))
            else:
                self._caps[name].update_methods(sorted(methods))

    def _record_timeout(self) -> bool:
        now = time.monotonic()
        self._timeout_events.append(now)
        window = max(1.0, self._timeout_window_s)
        self._timeout_events = [t for t in self._timeout_events if now - t <= window]
        return len(self._timeout_events) >= max(1, self._timeout_limit)

    def _restart(self, reason: str) -> None:
        if self._restart_count >= max(1, self._restart_max):
            raise PluginError(f"Plugin watchdog restart limit reached ({reason})")
        self._restart_count += 1
        if self._restart_backoff_s:
            time.sleep(max(0.0, float(self._restart_backoff_s)))
        self.close()
        self._start_host()

    def _call(self, capability: str, function: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        if self._host is None:
            self._start_host()
        for attempt in range(2):
            try:
                assert self._host is not None
                return self._host.call(capability, function, args, kwargs)
            except PluginTimeoutError:
                should_restart = self._record_timeout()
                if should_restart:
                    self._restart("rpc_timeout")
                    if attempt == 0:
                        continue
                raise

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
