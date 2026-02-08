"""Subprocess plugin host implementation."""

from __future__ import annotations

import atexit
import json
import os
import queue
import signal
import sys
import threading
import time
import weakref
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path
from typing import Any, IO, TYPE_CHECKING

from autocapture_nx.kernel.audit import (
    PluginAuditLog,
    append_audit_event,
    estimate_rows_read,
    estimate_rows_written,
    hash_payload,
)
from autocapture_nx.kernel.errors import PermissionError, PluginError, PluginTimeoutError
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.plugin_system.runtime import filesystem_guard_suspended
from autocapture_nx.plugin_system.sandbox import spawn_plugin_process, validate_ipc_message, write_sandbox_report

if TYPE_CHECKING:
    from subprocess import Popen


def _is_wsl() -> bool:
    if os.getenv("WSL_INTEROP") or os.getenv("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return False


_SUBPROCESS_INSTANCES: "weakref.WeakSet[SubprocessPlugin]" = weakref.WeakSet()
_SUBPROCESS_INSTANCES_LOCK = threading.Lock()
_SUBPROCESS_REAPER_THREAD: threading.Thread | None = None
_SUBPROCESS_REAPER_STOP = threading.Event()
_SUBPROCESS_LAST_REAP_MONO = 0.0
_SUBPROCESS_SPAWN_CV = threading.Condition()
_SUBPROCESS_SPAWN_ACTIVE = 0


def _notify_subprocess_host_slot_change() -> None:
    # Wake any threads waiting to spawn a new host due to cap pressure.
    try:
        with _SUBPROCESS_SPAWN_CV:
            _SUBPROCESS_SPAWN_CV.notify_all()
    except Exception:
        return


def _spawn_concurrency_from_config(config: dict[str, Any]) -> int:
    hosting = _hosting_cfg(config)
    env = os.getenv("AUTOCAPTURE_PLUGINS_SUBPROCESS_SPAWN_CONCURRENCY", "").strip()
    wsl = _is_wsl()
    default = 1 if wsl else 8
    cap = int(hosting.get("subprocess_spawn_concurrency", default) or default)
    if env:
        try:
            cap = int(env)
        except Exception:
            pass
    if cap < 1:
        cap = 1
    return cap


def _acquire_spawn_slot(*, config: dict[str, Any], wait_timeout_s: float) -> None:
    """Limit concurrent host_runner spawns to avoid WSL OOM spikes."""
    global _SUBPROCESS_SPAWN_ACTIVE
    cap = _spawn_concurrency_from_config(config)
    deadline = time.monotonic() + max(0.0, float(wait_timeout_s))
    while True:
        with _SUBPROCESS_SPAWN_CV:
            if _SUBPROCESS_SPAWN_ACTIVE < cap:
                _SUBPROCESS_SPAWN_ACTIVE += 1
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PluginTimeoutError(
                    f"subprocess spawn concurrency cap reached (active={_SUBPROCESS_SPAWN_ACTIVE} cap={cap})"
                )
            _SUBPROCESS_SPAWN_CV.wait(timeout=min(0.25, remaining))


def _release_spawn_slot() -> None:
    global _SUBPROCESS_SPAWN_ACTIVE
    try:
        with _SUBPROCESS_SPAWN_CV:
            _SUBPROCESS_SPAWN_ACTIVE = max(0, int(_SUBPROCESS_SPAWN_ACTIVE) - 1)
            _SUBPROCESS_SPAWN_CV.notify_all()
    except Exception:
        return


def _subprocess_limits_from_config(config: dict[str, Any]) -> tuple[int, float]:
    """Return (max_hosts, idle_ttl_s) for subprocess plugin hosts.

    Defaults prioritize WSL stability. Limits are best-effort: they must not
    cause the kernel to crash, but may reduce performance under extreme plugin
    fanout. Callers can override via config/env.
    """

    hosting = _hosting_cfg(config)
    env_max = os.getenv("AUTOCAPTURE_PLUGINS_SUBPROCESS_MAX_HOSTS", "").strip()
    env_ttl = os.getenv("AUTOCAPTURE_PLUGINS_SUBPROCESS_IDLE_TTL_S", "").strip()
    wsl = _is_wsl()

    # WSL default: keep the ceiling low. A single host_runner can be hundreds of
    # MB RSS depending on imported deps; spawning many in a burst can OOM WSL.
    default_max = 2 if wsl else 64
    default_ttl = 15.0 if wsl else 600.0

    max_hosts = int(hosting.get("subprocess_max_hosts", default_max) or default_max)
    idle_ttl_s = float(hosting.get("subprocess_idle_ttl_s", default_ttl) or default_ttl)

    if env_max:
        try:
            max_hosts = int(env_max)
        except Exception:
            pass
    if env_ttl:
        try:
            idle_ttl_s = float(env_ttl)
        except Exception:
            pass

    if max_hosts < 0:
        max_hosts = 0
    if idle_ttl_s < 0:
        idle_ttl_s = 0.0
    return max_hosts, idle_ttl_s


def reap_subprocess_hosts(
    *,
    force: bool = False,
    bypass_interval_gate: bool = False,
    now_mono: float | None = None,
) -> dict[str, Any]:
    """Best-effort reaper for subprocess plugin hosts.

    This prevents long-lived kernels from accumulating one host_runner process
    per plugin forever (especially painful on WSL). It is deliberately
    conservative: it only closes idle hosts (no in-flight RPC).
    """

    global _SUBPROCESS_LAST_REAP_MONO
    now = float(now_mono if now_mono is not None else time.monotonic())
    if not (force or bypass_interval_gate) and (now - float(_SUBPROCESS_LAST_REAP_MONO or 0.0)) < 0.8:
        with _SUBPROCESS_INSTANCES_LOCK:
            remaining = sum(1 for inst in _SUBPROCESS_INSTANCES if getattr(inst, "_host", None) is not None)
        return {
            "closed_ttl": 0,
            "closed_cap": 0,
            "remaining": remaining,
            "max_hosts": 0,
            "idle_ttl_s": 0.0,
            "force": False,
            "bypass_interval_gate": False,
            "skipped": True,
        }
    _SUBPROCESS_LAST_REAP_MONO = now
    closed_ttl = 0
    closed_cap = 0
    max_hosts = 0
    idle_ttl_s = 0.0

    with _SUBPROCESS_INSTANCES_LOCK:
        instances = [inst for inst in list(_SUBPROCESS_INSTANCES) if inst is not None]

    # Derive a conservative global limit across instances in this process.
    # Different kernels/tests may load different configs; we bias toward safety.
    for inst in instances:
        try:
            inst_max, inst_ttl = _subprocess_limits_from_config(getattr(inst, "_config", {}) or {})
        except Exception:
            continue
        if inst_max > 0:
            max_hosts = inst_max if max_hosts == 0 else min(max_hosts, inst_max)
        if inst_ttl > 0:
            idle_ttl_s = inst_ttl if idle_ttl_s == 0 else min(idle_ttl_s, inst_ttl)

    # TTL close.
    if idle_ttl_s > 0 or force:
        for inst in instances:
            host = getattr(inst, "_host", None)
            if host is None:
                continue
            try:
                in_flight = int(getattr(inst, "_in_flight", 0) or 0)
            except Exception:
                in_flight = 0
            if in_flight > 0:
                continue
            last_used = float(getattr(inst, "_last_used_mono", 0.0) or 0.0)
            if not force and idle_ttl_s > 0 and (now - last_used) <= idle_ttl_s:
                continue
            try:
                inst._close_host_for_reap(reason="idle_ttl" if not force else "force_reap")  # type: ignore[attr-defined]
                closed_ttl += 1
            except Exception:
                continue

    # Cap enforcement: if still above cap, evict LRU idle hosts.
    if max_hosts > 0:
        active = []
        for inst in instances:
            host = getattr(inst, "_host", None)
            if host is None:
                continue
            try:
                in_flight = int(getattr(inst, "_in_flight", 0) or 0)
            except Exception:
                in_flight = 0
            if in_flight > 0:
                continue
            last_used = float(getattr(inst, "_last_used_mono", 0.0) or 0.0)
            active.append((last_used, inst))
        if len(active) > max_hosts:
            active.sort(key=lambda item: item[0])  # oldest first
            to_close = max(0, len(active) - max_hosts)
            for _i in range(to_close):
                _last_used, inst = active[_i]
                try:
                    inst._close_host_for_reap(reason="host_cap")  # type: ignore[attr-defined]
                    closed_cap += 1
                except Exception:
                    continue
            if closed_cap:
                _notify_subprocess_host_slot_change()

    with _SUBPROCESS_INSTANCES_LOCK:
        remaining = sum(1 for inst in _SUBPROCESS_INSTANCES if getattr(inst, "_host", None) is not None)
    return {
        "closed_ttl": closed_ttl,
        "closed_cap": closed_cap,
        "remaining": remaining,
        "max_hosts": max_hosts,
        "idle_ttl_s": idle_ttl_s,
        "force": bool(force),
        "bypass_interval_gate": bool(bypass_interval_gate),
    }


def _ensure_subprocess_reaper_started() -> None:
    global _SUBPROCESS_REAPER_THREAD
    if _SUBPROCESS_REAPER_THREAD and _SUBPROCESS_REAPER_THREAD.is_alive():
        return
    with _SUBPROCESS_INSTANCES_LOCK:
        if _SUBPROCESS_REAPER_THREAD and _SUBPROCESS_REAPER_THREAD.is_alive():
            return
        _SUBPROCESS_REAPER_STOP.clear()

        def _loop() -> None:
            while not _SUBPROCESS_REAPER_STOP.is_set():
                try:
                    reap_subprocess_hosts(force=False)
                except Exception:
                    pass
                # Keep overhead low but responsive enough for WSL.
                _SUBPROCESS_REAPER_STOP.wait(timeout=1.0)

        _SUBPROCESS_REAPER_THREAD = threading.Thread(target=_loop, daemon=True, name="autocapture-subprocess-host-reaper")
        _SUBPROCESS_REAPER_THREAD.start()


def close_all_subprocess_hosts(*, reason: str = "shutdown") -> dict[str, Any]:
    """Close all idle subprocess hosts (best-effort).

    Used by kernel shutdown paths and tests to avoid host_runner process leaks.
    """

    try:
        return reap_subprocess_hosts(force=True, bypass_interval_gate=True)
    except Exception:
        return {"ok": False, "reason": str(reason)}


def _encode(obj: Any) -> Any:
    if isinstance(obj, (bytes, bytearray)):
        import base64

        return {"__bytes__": base64.b64encode(obj).decode("ascii")}
    if obj.__class__.__name__ == "CapabilityProxy":
        return {"__capability_proxy__": True, "repr": str(obj)}
    if is_dataclass(obj) and not isinstance(obj, type):
        return _encode(asdict(obj))
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, tuple):
        return [_encode(v) for v in obj]
    if isinstance(obj, set):
        return [_encode(v) for v in obj]
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


def _sanitize_plugin_id(plugin_id: str) -> str:
    # Prevent path traversal and keep per-plugin cache directories predictable.
    value = str(plugin_id).strip() or "plugin"
    value = value.replace("\\", "_").replace("/", "_")
    return "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in value)


def _cache_dir(hosting: dict[str, Any], config: dict[str, Any], plugin_id: str) -> Path:
    raw = hosting.get("cache_dir")
    base = Path(str(raw)) if raw else Path(str(config.get("storage", {}).get("data_dir", "data"))) / "cache" / "plugins"
    # Split caches by plugin to avoid cross-plugin interference and to let the
    # filesystem policy grant a narrow scratch write root.
    return base / _sanitize_plugin_id(plugin_id)


def _build_env(hosting: dict[str, Any], config: dict[str, Any], plugin_id: str) -> dict[str, str] | None:
    if not bool(hosting.get("sanitize_env", True)):
        return None
    env = os.environ.copy()
    if "AUTOCAPTURE_ROOT" not in env:
        try:
            env["AUTOCAPTURE_ROOT"] = str(resolve_repo_path("."))
        except Exception:
            env["AUTOCAPTURE_ROOT"] = str(Path(__file__).absolute().parents[2])
    repo_root = env.get("AUTOCAPTURE_ROOT", "")
    if repo_root:
        existing = env.get("PYTHONPATH", "")
        entries = [item for item in existing.split(os.pathsep) if item]
        if repo_root not in entries:
            env["PYTHONPATH"] = os.pathsep.join([repo_root, *entries]) if entries else repo_root
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

    cache_dir = _cache_dir(hosting, config, plugin_id)
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
    methods: list[str] | None

    def __getattr__(self, item: str):
        methods = self.methods
        if methods is not None and item not in methods:
            raise AttributeError(item)

        def _call(*args, **kwargs):
            return self.host._call(self.name, item, list(args), dict(kwargs))

        return _call

    def update_methods(self, methods: list[str] | None) -> None:
        self.methods = None if methods is None else list(methods)


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
        rng_seed: int | None = None,
        rng_seed_hex: str | None = None,
        rng_strict: bool = True,
        rng_enabled: bool = False,
    ) -> None:
        hosting = _hosting_cfg(host_config)
        self._rpc_timeout_s = float(hosting.get("rpc_timeout_s", 10))
        self._rpc_startup_timeout_s = float(hosting.get("rpc_startup_timeout_s", self._rpc_timeout_s))
        self._rpc_max_message_bytes = int(hosting.get("rpc_max_message_bytes", 2_000_000))
        self._write_lock = threading.Lock()
        self._response_lock = threading.Lock()
        self._responses: dict[int, queue.Queue] = {}
        self._reader_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._reader_error: str | None = None
        self._capabilities = capabilities
        self._allowed_capabilities = set(allowed_capabilities) if allowed_capabilities is not None else None
        self._plugin_id = plugin_id
        self._filesystem_policy = filesystem_policy
        self._proc: Popen[str] | None = None

        python_exe = _resolve_python_exe()
        proc, self._sandbox_report = spawn_plugin_process(
            [
                python_exe,
                "-m",
                "autocapture_nx.plugin_system.host_runner",
                str(plugin_path),
                callable_name,
                plugin_id,
                "true" if network_allowed else "false",
            ],
            env=_build_env(hosting, host_config, plugin_id),
            limits=_adjust_job_limits_for_venv(python_exe, hosting.get("job_limits", {})),
            ipc_max_bytes=self._rpc_max_message_bytes,
        )
        self._proc = proc
        if proc.stdin is None or proc.stdout is None:
            raise PluginError("Failed to start plugin host")
        write_sandbox_report(self._sandbox_report)
        self._stdin: IO[str] = proc.stdin
        self._stdout: IO[str] = proc.stdout
        self._req_id = 0
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        init_payload: dict[str, Any] = {"config": plugin_config, "host_config": host_config}
        init_payload["allowed_capabilities"] = (
            None if self._allowed_capabilities is None else sorted(self._allowed_capabilities)
        )
        init_payload["filesystem_policy"] = self._filesystem_policy
        init_payload["rng"] = {
            "enabled": bool(rng_enabled),
            "strict": bool(rng_strict),
            "seed": rng_seed,
            "seed_hex": rng_seed_hex,
        }
        self._send_payload(init_payload, enforce_limit=False)

    def _send_payload(self, payload: dict[str, Any], *, enforce_limit: bool = True) -> None:
        text = json.dumps(payload)
        size = len(text.encode("utf-8"))
        if enforce_limit and size > self._rpc_max_message_bytes:
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
                ok, reason = validate_ipc_message(response, role="host")
                if not ok:
                    self._set_reader_error(f"ipc_validation_failed:{reason}")
                    return
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
                    if os.name != "nt":
                        # Prefer killing the whole process group so children don't linger.
                        try:
                            os.killpg(proc.pid, signal.SIGTERM)
                        except Exception:
                            proc.terminate()
                    else:
                        proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        if os.name != "nt":
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                            except Exception:
                                proc.kill()
                        else:
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

    def _request(self, payload: dict[str, Any], *, timeout_s: float | None = None) -> Any:
        if self._reader_error:
            raise PluginError(self._reader_error)
        self._req_id += 1
        req_id = self._req_id
        payload["id"] = req_id
        resp_q: queue.Queue = queue.Queue(maxsize=1)
        with self._response_lock:
            self._responses[req_id] = resp_q
        self._send_payload(payload)
        timeout = max(0.1, float(timeout_s if timeout_s is not None else self._rpc_timeout_s))
        try:
            response = resp_q.get(timeout=timeout)
        except queue.Empty as exc:
            self.close()
            raise PluginTimeoutError(
                f"Plugin host request timed out after {timeout:.2f}s (plugin={self._plugin_id})"
            ) from exc
        finally:
            with self._response_lock:
                self._responses.pop(req_id, None)
        if not response.get("ok"):
            error = response.get("error", "unknown error")
            tb = response.get("traceback")
            if tb:
                error = f"{error}\n{tb}"
            raise PluginError(error)
        return response.get("result")

    def capabilities(self) -> dict[str, list[str]]:
        return self._request({"method": "capabilities"}, timeout_s=self._rpc_startup_timeout_s)

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
        entrypoint_kind: str | None = None,
        provided_capabilities: list[str] | None = None,
        rng_seed: int | None = None,
        rng_seed_hex: str | None = None,
        rng_strict: bool = True,
        rng_enabled: bool = False,
        audit_log: PluginAuditLog | None = None,
        code_hash: str | None = None,
        settings_hash: str | None = None,
    ):
        self._plugin_path = plugin_path
        self._callable_name = callable_name
        self._plugin_id = plugin_id
        self._network_allowed = network_allowed
        self._config = config
        self._plugin_config = plugin_config if isinstance(plugin_config, dict) else config
        self.settings = dict(self._plugin_config)
        self._capabilities = capabilities
        self._allowed_capabilities = allowed_capabilities
        self._filesystem_policy = filesystem_policy
        self._rng_seed = rng_seed
        self._rng_seed_hex = rng_seed_hex
        self._rng_strict = bool(rng_strict)
        self._rng_enabled = bool(rng_enabled)
        self._audit_log = audit_log
        self._code_hash = code_hash
        self._settings_hash = settings_hash
        hosting = _hosting_cfg(config)
        self._timeout_limit = int(hosting.get("rpc_timeout_limit", 3))
        self._timeout_window_s = float(hosting.get("rpc_timeout_window_s", 60))
        self._restart_backoff_s = float(hosting.get("rpc_watchdog_backoff_s", 0.2))
        self._restart_max = int(hosting.get("rpc_watchdog_restart_max", 3))
        self._timeout_events: list[float] = []
        self._failure_limit = int(hosting.get("rpc_failure_limit", self._timeout_limit))
        self._failure_window_s = float(hosting.get("rpc_failure_window_s", self._timeout_window_s))
        self._failure_cooldown_s = float(hosting.get("rpc_failure_cooldown_s", self._restart_backoff_s or 0.0))
        self._failure_events: list[float] = []
        self._cooldown_until = 0.0
        self._restart_count = 0
        self._host: PluginProcess | None = None
        self._caps: dict[str, RemoteCapability] = {}
        self._cap_methods: dict[str, set[str]] = {}
        self._in_flight = 0
        self._last_used_mono = time.monotonic()
        self._capabilities_probe_only = False

        # Register early so the reaper/cap logic can observe this instance even
        # during init-time host startups (important for WSL stability).
        with _SUBPROCESS_INSTANCES_LOCK:
            _SUBPROCESS_INSTANCES.add(self)
        _ensure_subprocess_reaper_started()

        lazy_start_env = os.getenv("AUTOCAPTURE_PLUGINS_LAZY_START", "1").strip().lower()
        self._lazy_start = lazy_start_env not in {"0", "false", "no"}
        # WSL stability guard: spawning a subprocess for every plugin during load
        # can exhaust RAM quickly. Default to lazy start on WSL even if the env var
        # was set to disable it, unless explicitly opted out via config.
        try:
            hosting = _hosting_cfg(config)
            wsl_force_lazy = bool(hosting.get("wsl_force_lazy_start", True))
        except Exception:
            wsl_force_lazy = True
        if not self._lazy_start and wsl_force_lazy and _is_wsl():
            self._lazy_start = True
        seed_entrypoint = str(entrypoint_kind).strip() if entrypoint_kind else ""
        # Some entrypoint kinds are plugin "types" rather than actual RPC capability names.
        # If we seed these, the registry will miss the real capability keys.
        kind_denylist = {"storage.metadata_store"}
        entrypoint_looks_like_cap = bool(seed_entrypoint and "." in seed_entrypoint and seed_entrypoint not in kind_denylist)

        if self._lazy_start and provided_capabilities:
            # Trust explicit `provides` as the set of capability keys the plugin exposes.
            for name in (str(item).strip() for item in provided_capabilities):
                if not name:
                    continue
                self._caps[name] = RemoteCapability(self, name, None)
        elif self._lazy_start and entrypoint_looks_like_cap:
            # Avoid spawning the subprocess host just to enumerate capabilities.
            # We'll start the host on first use and refresh method lists then.
            self._caps[seed_entrypoint] = RemoteCapability(self, seed_entrypoint, None)
        else:
            self._start_host()
        atexit.register(self.close)

    def capabilities(self) -> dict[str, Any]:
        # Back-compat: if the manifest didn't specify `provides`, we must enumerate
        # capabilities from the plugin itself, which requires starting the host.
        if not self._caps and self._host is None:
            self._capabilities_probe_only = True
            self._start_host()
        return self._caps

    def close(self) -> None:
        if getattr(self, "_host", None) is None:
            return
        try:
            assert self._host is not None
            self._host.close()
        finally:
            self._host = None
            _notify_subprocess_host_slot_change()

    def _close_host_for_reap(self, *, reason: str) -> None:
        host = getattr(self, "_host", None)
        if host is None:
            return
        pid = getattr(getattr(host, "_proc", None), "pid", None)
        try:
            host.close()
        finally:
            self._host = None
            _notify_subprocess_host_slot_change()
        try:
            append_audit_event(
                action="plugin.host.reap",
                actor="plugin_system",
                outcome="ok",
                details={"plugin_id": self._plugin_id, "reason": str(reason), "pid": pid},
            )
        except Exception:
            pass

    def _start_host(self) -> None:
        # Treat starting a host as "use" so LRU eviction does not immediately
        # reap the fresh host under cap pressure.
        self._last_used_mono = time.monotonic()
        # Before spawning another host_runner, ensure the reaper's cap/TTL logic
        # actually runs. The background reaper uses an interval gate to keep
        # overhead low, but bursty startup must not bypass the cap (WSL OOM).
        try:
            reap_subprocess_hosts(force=False, bypass_interval_gate=True)
        except Exception:
            pass
        wait_s = float(os.getenv("AUTOCAPTURE_PLUGINS_SUBPROCESS_SPAWN_WAIT_S", "10") or 10)
        _acquire_spawn_slot(config=self._config, wait_timeout_s=wait_s)
        try:
            with filesystem_guard_suspended():
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
                    rng_seed=self._rng_seed,
                    rng_seed_hex=self._rng_seed_hex,
                    rng_strict=self._rng_strict,
                    rng_enabled=self._rng_enabled,
                )
                self._refresh_caps()
        finally:
            _release_spawn_slot()
        # Enforce the host cap promptly after a spawn to prevent slow buildup
        # in bursty startup scenarios (especially WSL).
        try:
            reap_subprocess_hosts(force=False, bypass_interval_gate=True)
        except Exception:
            pass
        try:
            pid = getattr(getattr(self._host, "_proc", None), "pid", None) if self._host is not None else None
            append_audit_event(
                action="plugin.host.start",
                actor="plugin_system",
                outcome="ok",
                details={"plugin_id": self._plugin_id, "pid": pid},
            )
        except Exception:
            pass

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

    def _record_failure(self) -> bool:
        now = time.monotonic()
        self._failure_events.append(now)
        window = max(1.0, self._failure_window_s)
        self._failure_events = [t for t in self._failure_events if now - t <= window]
        return len(self._failure_events) >= max(1, self._failure_limit)

    def _open_circuit(self, now: float) -> None:
        cooldown = max(0.0, float(self._failure_cooldown_s))
        if cooldown <= 0:
            return
        self._cooldown_until = max(self._cooldown_until, now + cooldown)

    def _in_cooldown(self) -> bool:
        return time.monotonic() < self._cooldown_until

    def _restart(self, reason: str) -> None:
        if self._restart_count >= max(1, self._restart_max):
            raise PluginError(f"Plugin watchdog restart limit reached ({reason})")
        self._restart_count += 1
        if self._restart_backoff_s:
            time.sleep(max(0.0, float(self._restart_backoff_s)))
        self.close()
        self._start_host()

    def _is_host_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "plugin host closed" in msg or "broken pipe" in msg or "host closed" in msg

    def _call(self, capability: str, function: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        self._last_used_mono = time.monotonic()
        self._in_flight += 1
        try:
            if self._host is None:
                self._start_host()
            elif self._lazy_start:
                cap_obj = self._caps.get(capability)
                if cap_obj is not None and cap_obj.methods is None:
                    try:
                        self._refresh_caps()
                    except Exception:
                        pass
            if self._in_cooldown():
                raise PluginError(f"Plugin circuit breaker open (plugin={self._plugin_id})")
            start = time.perf_counter()
            mem_before = self._memory_snapshot_mb()
            ok = False
            result: Any = None
            error_text: str | None = None
            for attempt in range(2):
                try:
                    assert self._host is not None
                    result = self._host.call(capability, function, args, kwargs)
                    self._failure_events.clear()
                    self._timeout_events.clear()
                    ok = True
                    return result
                except PluginTimeoutError:
                    should_restart = self._record_timeout()
                    if should_restart:
                        self._restart("rpc_timeout")
                        if attempt == 0:
                            continue
                    now = time.monotonic()
                    if self._record_failure():
                        self._open_circuit(now)
                    error_text = "timeout"
                    raise
                except PluginError as exc:
                    now = time.monotonic()
                    should_restart = self._record_failure()
                    if self._is_host_error(exc) and attempt == 0:
                        try:
                            self._restart("host_error")
                            continue
                        except Exception:
                            pass
                    if should_restart:
                        self._open_circuit(now)
                    error_text = str(exc)
                    raise
                finally:
                    if attempt == 0 and self._audit_log is not None:
                        self._record_audit(
                            capability=capability,
                            function=function,
                            args=args,
                            kwargs=kwargs,
                            result=result if ok else None,
                            ok=ok,
                            error_text=error_text,
                            start=start,
                            mem_before=mem_before,
                        )
        finally:
            self._last_used_mono = time.monotonic()
            self._in_flight = max(0, int(self._in_flight) - 1)
            try:
                # Avoid interval-gate skips on bursty workloads (tests/oneshots).
                reap_subprocess_hosts(force=False, bypass_interval_gate=True)
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _memory_snapshot_mb(self) -> tuple[int | None, int | None]:
        host = self._host
        proc = getattr(host, "_proc", None) if host is not None else None
        if proc is None or proc.pid is None:
            return None, None
        try:
            import psutil  # type: ignore

            info = psutil.Process(proc.pid).memory_info()
            return int(info.rss // (1024 * 1024)), int(info.vms // (1024 * 1024))
        except Exception:
            return None, None

    def _record_audit(
        self,
        *,
        capability: str,
        function: str,
        args: list[Any],
        kwargs: dict[str, Any],
        result: Any,
        ok: bool,
        error_text: str | None,
        start: float,
        mem_before: tuple[int | None, int | None],
    ) -> None:
        if self._audit_log is None:
            return
        duration_ms = int(max(0.0, (time.perf_counter() - start) * 1000.0))
        mem_after = self._memory_snapshot_mb()
        rss_mb = mem_after[0] if mem_after[0] is not None else mem_before[0]
        vms_mb = mem_after[1] if mem_after[1] is not None else mem_before[1]
        input_hash, input_bytes = hash_payload({"args": args, "kwargs": kwargs})
        output_hash, output_bytes = hash_payload(result) if ok else (None, None)
        data_hash, _ = hash_payload({"input": input_hash, "output": output_hash})
        rows_written = estimate_rows_written(function, args, kwargs)
        rows_read = estimate_rows_read(function, result) if ok else None
        run_id = str(self._config.get("runtime", {}).get("run_id", "")) or "run"
        try:
            self._audit_log.record(
                run_id=run_id,
                plugin_id=self._plugin_id,
                capability=str(capability),
                method=str(function),
                ok=ok,
                error=error_text,
                duration_ms=duration_ms,
                rows_read=rows_read,
                rows_written=rows_written,
                memory_rss_mb=rss_mb,
                memory_vms_mb=vms_mb,
                input_hash=input_hash,
                output_hash=output_hash,
                data_hash=data_hash,
                code_hash=self._code_hash,
                settings_hash=self._settings_hash,
                input_bytes=input_bytes,
                output_bytes=output_bytes,
            )
        except Exception:
            return
