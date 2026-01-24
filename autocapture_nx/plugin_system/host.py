"""Subprocess plugin host implementation."""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
        self._proc = subprocess.Popen(
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
        )
        if self._proc.stdin is None or self._proc.stdout is None:
            raise PluginError("Failed to start plugin host")
        assign_job_object(self._proc.pid)
        self._stdin = self._proc.stdin
        self._stdout = self._proc.stdout
        self._req_id = 0
        self._stdin.write(json.dumps(config) + "\n")
        self._stdin.flush()

    def close(self) -> None:
        proc = getattr(self, "_proc", None)
        if proc is None:
            return
        try:
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
            for stream in (getattr(self, "_stdin", None), getattr(self, "_stdout", None)):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            self._proc = None

    def _request(self, payload: dict[str, Any]) -> Any:
        self._req_id += 1
        payload["id"] = self._req_id
        self._stdin.write(json.dumps(payload) + "\n")
        self._stdin.flush()
        line = self._stdout.readline()
        if not line:
            raise PluginError("Plugin host closed")
        response = json.loads(line)
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
        self._host = PluginProcess(plugin_path, callable_name, plugin_id, network_allowed, config)
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
            self._host.close()
        finally:
            self._host = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
