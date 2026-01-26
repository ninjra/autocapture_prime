"""Subprocess plugin host runner."""

from __future__ import annotations

import importlib.util
import json
import sys
from typing import Any

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.plugin_system.runtime import network_guard


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


def main() -> None:
    if len(sys.argv) < 5:
        raise SystemExit("usage: host_runner <plugin_path> <callable> <plugin_id> <network_allowed>")
    plugin_path, callable_name, plugin_id, network_allowed_text = sys.argv[1:5]
    network_allowed = network_allowed_text.lower() == "true"

    spec = importlib.util.spec_from_file_location("plugin_module", plugin_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load plugin module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plugin_module"] = module
    spec.loader.exec_module(module)  # type: ignore[call-arg]
    factory = getattr(module, callable_name)

    context = PluginContext(config=json.loads(sys.stdin.readline()), get_capability=lambda _k: None, logger=lambda _m: None)
    with network_guard(network_allowed):
        instance = factory(plugin_id, context)
        caps = instance.capabilities()

    cap_map = {name: cap for name, cap in caps.items()}

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        request = json.loads(line)
        req_id = request.get("id")
        method = request.get("method")
        try:
            if method == "capabilities":
                result = {name: [m for m in dir(obj) if callable(getattr(obj, m)) and not m.startswith("_")] for name, obj in cap_map.items()}
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
            response = {"id": req_id, "ok": False, "error": str(exc)}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
