"""External vLLM endpoint policy and probe helpers."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

EXTERNAL_VLLM_BASE_URL = "http://127.0.0.1:8000"
_ALLOWED_SCHEME = "http"
_ALLOWED_HOST = "127.0.0.1"
_ALLOWED_PORT = 8000


def enforce_external_vllm_base_url(candidate: str | None) -> str:
    """Return canonical external base URL or raise on policy violation."""
    raw = str(candidate or "").strip()
    if not raw:
        return EXTERNAL_VLLM_BASE_URL
    parsed = urllib.parse.urlparse(raw)
    scheme = str(parsed.scheme or "").strip().lower()
    host = str(parsed.hostname or "").strip()
    port = int(parsed.port or (_ALLOWED_PORT if scheme == _ALLOWED_SCHEME else 0))
    if scheme != _ALLOWED_SCHEME:
        raise ValueError(f"invalid_vllm_scheme:{scheme or 'missing'}")
    if host != _ALLOWED_HOST:
        raise ValueError(f"invalid_vllm_host:{host or 'missing'}")
    if port != _ALLOWED_PORT:
        raise ValueError(f"invalid_vllm_port:{port}")
    return EXTERNAL_VLLM_BASE_URL


def check_external_vllm_ready(*, timeout_health_s: float = 3.0, timeout_models_s: float = 4.0) -> dict[str, Any]:
    """Probe required external vLLM routes on localhost:8000.

    This repo consumes external vLLM only. No lifecycle actions are performed here.
    """
    out: dict[str, Any] = {"ok": False, "base_url": EXTERNAL_VLLM_BASE_URL}
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(f"{EXTERNAL_VLLM_BASE_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=float(timeout_health_s)) as resp:
            out["health_status"] = int(getattr(resp, "status", 0))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        out["error"] = f"health_unreachable:{type(exc).__name__}"
        out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
        return out
    try:
        req = urllib.request.Request(f"{EXTERNAL_VLLM_BASE_URL}/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=float(timeout_models_s)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        out["error"] = f"models_unreachable:{type(exc).__name__}"
        out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
        return out
    models: list[str] = []
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                model_id = str(item.get("id") or "").strip()
                if model_id:
                    models.append(model_id)
    out["models"] = models
    out["ok"] = bool(models)
    if not out["ok"]:
        out["error"] = "models_empty"
    out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
    return out
