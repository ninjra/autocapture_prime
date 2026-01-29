"""Subprocess plugin host runner with capability bridging."""

from __future__ import annotations

import importlib.util
import json
import queue
import sys
import threading
from typing import Any

from autocapture_nx.kernel.errors import PermissionError, PluginError
from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.plugin_system.runtime import (
    FilesystemPolicy,
    network_guard,
    set_global_filesystem_policy,
    set_global_network_deny,
)


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
    if isinstance(init_payload, dict) and "config" in init_payload:
        config = init_payload.get("config", {})
        host_config = init_payload.get("host_config", config)
        allowed_caps = _allowed_caps(init_payload.get("allowed_capabilities"))
        fs_policy = _filesystem_policy(init_payload.get("filesystem_policy"))
    else:
        config = init_payload if isinstance(init_payload, dict) else {}
        host_config = config
        allowed_caps = None
        fs_policy = None

    set_global_filesystem_policy(fs_policy)

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

    spec = importlib.util.spec_from_file_location("plugin_module", plugin_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load plugin module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plugin_module"] = module
    spec.loader.exec_module(module)  # type: ignore[call-arg]
    factory = getattr(module, callable_name)

    context = PluginContext(config=config, get_capability=_get_capability, logger=lambda _m: None)
    with network_guard(network_allowed):
        instance = factory(plugin_id, context)
        caps = instance.capabilities()

    cap_map = {name: cap for name, cap in caps.items()}

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
                        result = func(*args, **kwargs)
                    result = _encode(result)
                else:
                    raise ValueError("unknown method")
                response = {"id": req_id, "ok": True, "result": result}
            except Exception as exc:
                response = {"id": req_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            bridge.send(response)
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
