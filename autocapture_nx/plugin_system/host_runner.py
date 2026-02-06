"""Subprocess plugin host runner with capability bridging."""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import sys
import threading
import random
import traceback
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.errors import PermissionError, PluginError
from autocapture_nx.kernel.rng import install_rng_guard, set_thread_seed
from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.plugin_system.runtime import (
    FilesystemPolicy,
    network_guard,
    set_global_filesystem_policy,
    set_global_network_deny,
)
from autocapture_nx.plugin_system.sandbox import validate_ipc_message


def _debug(message: str) -> None:
    if os.getenv("AUTOCAPTURE_HOST_DEBUG", ""):
        sys.stderr.write(f"[host_runner] {message}\n")
        sys.stderr.flush()


def _host_log_path(config: dict[str, Any], plugin_id: str) -> Path | None:
    try:
        storage = config.get("storage", {}) if isinstance(config, dict) else {}
        data_dir = storage.get("data_dir", "data")
        runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
        run_id = runtime.get("run_id", "run")
        run_dir = Path(str(data_dir)) / "runs" / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir / f"plugin_host_{plugin_id}.log"
    except Exception:
        return None


def _log_host_error(config: dict[str, Any], plugin_id: str, message: str) -> None:
    path = _host_log_path(config, plugin_id)
    if not path:
        return
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        return


def _decode(obj: Any) -> Any:
    if isinstance(obj, dict) and "__bytes__" in obj:
        import base64

        return base64.b64decode(obj["__bytes__"])
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _decode(v) for k, v in obj.items()}
    return obj


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


def _hosting_cfg(config: dict[str, Any]) -> dict[str, Any]:
    plugins = config.get("plugins", {}) if isinstance(config, dict) else {}
    hosting = plugins.get("hosting", {})
    return hosting if isinstance(hosting, dict) else {}


class _Bridge:
    def __init__(self, rpc_timeout_s: float, rpc_max_message_bytes: int) -> None:
        self._rpc_timeout_s = max(0.1, float(rpc_timeout_s))
        self._rpc_max_message_bytes = max(1024, int(rpc_max_message_bytes))
        self._write_lock = threading.Lock()
        self._req_id = 0
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._requests: queue.Queue[Any] = queue.Queue()
        self._stop = threading.Event()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_error: str | None = None

    def start(self) -> None:
        self._reader_thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self._requests.put_nowait(None)
        except Exception:
            pass
        if self._reader_thread.is_alive():
            try:
                self._reader_thread.join(timeout=1)
            except Exception:
                pass

    def _set_error(self, message: str) -> None:
        if self._reader_error:
            return
        self._reader_error = message
        with self._pending_lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for req_id, resp_q in pending:
            try:
                resp_q.put_nowait({"id": req_id, "ok": False, "error": message, "response_to": "cap_call"})
            except Exception:
                pass
        try:
            self._requests.put_nowait(None)
        except Exception:
            pass

    def _check_size(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload)
        size = len(text.encode("utf-8"))
        if size > self._rpc_max_message_bytes:
            raise PluginError(f"payload too large ({size} bytes)")

    def send(self, payload: dict[str, Any]) -> None:
        payload = _encode(payload)
        self._check_size(payload)
        with self._write_lock:
            sys.stdout.write(json.dumps(payload) + "\n")
            sys.stdout.flush()

    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            line = sys.stdin.readline()
            if not line:
                self._set_error("host closed")
                return
            size = len(line.encode("utf-8"))
            if size > self._rpc_max_message_bytes:
                self._set_error(f"message too large ({size} bytes)")
                return
            try:
                message = json.loads(line)
            except Exception as exc:
                self._set_error(f"invalid message: {exc}")
                return
            ok, reason = validate_ipc_message(message, role="plugin")
            if not ok:
                self._set_error(f"ipc_validation_failed:{reason}")
                return
            if message.get("response_to") == "cap_call":
                req_id = int(message.get("id", 0))
                with self._pending_lock:
                    resp_q = self._pending.get(req_id)
                if resp_q is not None:
                    try:
                        resp_q.put_nowait(message)
                    except Exception:
                        pass
                continue
            try:
                self._requests.put_nowait(message)
            except Exception:
                self._set_error("request queue full")
                return

    def next_request(self) -> dict[str, Any] | None:
        if self._reader_error:
            raise PluginError(self._reader_error)
        item = self._requests.get()
        if item is None:
            return None
        return item

    def cap_call(
        self,
        capability: str,
        function: str,
        args: list[Any],
        kwargs: dict[str, Any],
    ) -> Any:
        if self._reader_error:
            raise PluginError(self._reader_error)
        self._req_id += 1
        req_id = self._req_id
        resp_q: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[req_id] = resp_q
        request = {
            "id": req_id,
            "method": "cap_call",
            "capability": capability,
            "function": function,
            "args": _encode(args),
            "kwargs": _encode(kwargs),
        }
        self.send(request)
        try:
            response = resp_q.get(timeout=self._rpc_timeout_s)
        except queue.Empty as exc:
            self.close()
            raise PluginError(f"capability call timed out after {self._rpc_timeout_s:.2f}s") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(req_id, None)
        if not response.get("ok"):
            raise PluginError(str(response.get("error", "capability call failed")))
        return _decode(response.get("result"))


class _CapabilityProxy:
    def __init__(self, bridge: _Bridge, capability: str) -> None:
        self._bridge = bridge
        self._capability = capability

    def __getattr__(self, item: str):
        if item.startswith("_"):
            raise AttributeError(item)

        def _call(*args, **kwargs):
            return self._bridge.cap_call(self._capability, item, list(args), dict(kwargs))

        return _call

    def __call__(self, *args, **kwargs):
        return self._bridge.cap_call(self._capability, "", list(args), dict(kwargs))


def _allowed_caps(payload: Any) -> set[str] | None:
    if payload is None:
        return None
    if isinstance(payload, list):
        return {str(item) for item in payload}
    return None


def _filesystem_policy(payload: Any) -> FilesystemPolicy | None:
    if not isinstance(payload, dict):
        return None
    read = payload.get("read", [])
    readwrite = payload.get("readwrite", [])
    if not isinstance(read, list) and not isinstance(readwrite, list):
        return None
    return FilesystemPolicy.from_paths(read=read if isinstance(read, list) else [], readwrite=readwrite if isinstance(readwrite, list) else [])


def _seed_optional_libs(seed: int) -> None:
    """Seed optional heavy deps without importing them.

    Importing torch in every subprocess host was causing large RSS (hundreds of MB)
    even for plugins that never touch torch. We only seed if the module is already
    loaded by the plugin.
    """

    np = sys.modules.get("numpy")
    if np is not None:
        try:
            getattr(np, "random").seed(seed)
        except Exception:
            pass
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            getattr(torch, "manual_seed")(seed)
        except Exception:
            pass


def main() -> None:
    if len(sys.argv) < 5:
        raise SystemExit("usage: host_runner <plugin_path> <callable> <plugin_id> <network_allowed>")
    plugin_path, callable_name, plugin_id, network_allowed_text = sys.argv[1:5]
    network_allowed = network_allowed_text.lower() == "true"
    set_global_network_deny(not network_allowed)

    init_line = sys.stdin.readline()
    if not init_line:
        raise SystemExit("missing init payload")
    init_payload = json.loads(init_line)
    _debug("init payload received")
    if isinstance(init_payload, dict) and "config" in init_payload:
        config = init_payload.get("config", {})
        host_config = init_payload.get("host_config", config)
        allowed_caps = _allowed_caps(init_payload.get("allowed_capabilities"))
        fs_policy = _filesystem_policy(init_payload.get("filesystem_policy"))
        rng_info = init_payload.get("rng", {}) if isinstance(init_payload, dict) else {}
    else:
        config = init_payload if isinstance(init_payload, dict) else {}
        host_config = config
        allowed_caps = None
        fs_policy = None
        rng_info = {}

    set_global_filesystem_policy(fs_policy)
    _debug("filesystem policy installed")
    _log_host_error(config, plugin_id, f"host_runner start: pid={os.getpid()} python={sys.executable}")

    rng_enabled = bool(rng_info.get("enabled", False))
    rng_seed_value = rng_info.get("seed")
    rng_strict = bool(rng_info.get("strict", True))
    rng_seed_hex = rng_info.get("seed_hex")
    rng_instance = None
    rng_seed_int: int | None = None
    if rng_enabled and rng_seed_value is not None:
        try:
            rng_seed_int = int(rng_seed_value)
        except Exception:
            rng_seed_int = 0
        install_rng_guard()
        set_thread_seed(rng_seed_int, strict=rng_strict)
        rng_instance = random.Random(rng_seed_int)

    if not isinstance(host_config, dict):
        host_config = {}
    hosting = _hosting_cfg(host_config)
    bridge = _Bridge(
        rpc_timeout_s=float(hosting.get("rpc_timeout_s", 10)),
        rpc_max_message_bytes=int(hosting.get("rpc_max_message_bytes", 2_000_000)),
    )
    bridge.start()

    def _get_capability(name: str) -> Any:
        cap = str(name)
        if allowed_caps is not None and cap not in allowed_caps:
            raise PermissionError(f"capability not allowed: {cap}")
        return _CapabilityProxy(bridge, cap)

    try:
        _debug(f"loading plugin module {plugin_path}")
        spec = importlib.util.spec_from_file_location("plugin_module", plugin_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Failed to load plugin module")
        module = importlib.util.module_from_spec(spec)
        sys.modules["plugin_module"] = module
        spec.loader.exec_module(module)  # type: ignore[call-arg]
        factory = getattr(module, callable_name)
        _debug("plugin module loaded")

        context = PluginContext(
            config=config,
            get_capability=_get_capability,
            logger=lambda _m: None,
            rng=rng_instance,
            rng_seed=rng_seed_int,
            rng_seed_hex=str(rng_seed_hex) if rng_seed_hex is not None else None,
        )
        trace_enabled = os.getenv("AUTOCAPTURE_HOST_TRACE", "")
        with network_guard(network_allowed):
            if trace_enabled:
                import faulthandler

                faulthandler.dump_traceback_later(5.0, repeat=False, file=sys.stderr)
            if rng_enabled and rng_seed_int is not None:
                _seed_optional_libs(rng_seed_int)
            instance = factory(plugin_id, context)
            if trace_enabled:
                import faulthandler

                faulthandler.cancel_dump_traceback_later()
            _debug("plugin instance created")
            caps = instance.capabilities()
            _debug("plugin capabilities collected")
    except Exception as exc:
        tb = traceback.format_exc()
        _log_host_error(config, plugin_id, f"plugin init error: {type(exc).__name__}: {exc}\n{tb}")
        raise

    cap_map = {name: cap for name, cap in caps.items()}
    _debug("entering request loop")

    try:
        while True:
            request = bridge.next_request()
            if request is None:
                break
            req_id = request.get("id")
            method = request.get("method")
            try:
                if method == "capabilities":
                    result = {
                        name: [m for m in dir(obj) if callable(getattr(obj, m)) and not m.startswith("_")]
                        for name, obj in cap_map.items()
                    }
                elif method == "call":
                    cap = cap_map[request["capability"]]
                    func = getattr(cap, request["function"])
                    args = _decode(request.get("args", []))
                    kwargs = _decode(request.get("kwargs", {}))
                    with network_guard(network_allowed):
                        if rng_enabled and rng_seed_int is not None:
                            _seed_optional_libs(rng_seed_int)
                        result = func(*args, **kwargs)
                    result = _encode(result)
                else:
                    raise ValueError("unknown method")
                response = {"id": req_id, "ok": True, "result": result}
            except Exception as exc:
                response = {
                    "id": req_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            bridge.send(response)
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
