"""Localhost-only OpenAI-compatible client helpers.

This is used for talking to local inference servers (eg vLLM) on 127.0.0.1.
It must never be used for non-loopback egress.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import json
import os
import socket
import threading
import urllib.parse
from dataclasses import dataclass
from typing import Any

from autocapture_nx.runtime.http_localhost import request_json


class LocalhostOnlyError(RuntimeError):
    pass


_VLM_GATE_LOCK = threading.Lock()
_VLM_GATE_SEM: threading.BoundedSemaphore | None = None
_VLM_GATE_LIMIT = 0


def _managed_vlm_max_inflight() -> int:
    raw = str(os.environ.get("AUTOCAPTURE_VLM_MAX_INFLIGHT") or "").strip()
    try:
        value = int(raw) if raw else 1
    except Exception:
        value = 1
    return max(1, min(64, value))


def _managed_vlm_semaphore() -> tuple[threading.BoundedSemaphore, int]:
    global _VLM_GATE_SEM, _VLM_GATE_LIMIT
    limit = _managed_vlm_max_inflight()
    with _VLM_GATE_LOCK:
        if _VLM_GATE_SEM is None or _VLM_GATE_LIMIT != limit:
            _VLM_GATE_SEM = threading.BoundedSemaphore(limit)
            _VLM_GATE_LIMIT = limit
        sem = _VLM_GATE_SEM
    assert sem is not None
    return sem, limit


def _is_managed_vlm_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
    except Exception:
        return False
    host = str(parsed.hostname or "").strip()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return False
    try:
        port = int(parsed.port or 80)
    except Exception:
        return False
    if port != 8000:
        return False
    path = str(parsed.path or "")
    return path.startswith("/v1/")


@contextmanager
def _maybe_managed_vlm_gate(*, url: str, timeout_s: float):
    if not _is_managed_vlm_url(url):
        yield
        return
    sem, limit = _managed_vlm_semaphore()
    wait_timeout = max(5.0, float(timeout_s) + 2.0)
    acquired = sem.acquire(timeout=wait_timeout)
    if not acquired:
        raise RuntimeError(f"vlm_gate_timeout:max_inflight={limit}")
    try:
        yield
    finally:
        sem.release()


def _is_loopback_host(host: str) -> bool:
    host = str(host or "").strip()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return True
    # Resolve to prevent "localhost-like" tricks; fail closed on resolution errors.
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        try:
            addr = info[4][0]
        except Exception:
            continue
        if not isinstance(addr, str):
            continue
        try:
            socket.inet_pton(socket.AF_INET, addr)
            if addr.startswith("127."):
                return True
        except Exception:
            pass
        try:
            socket.inet_pton(socket.AF_INET6, addr)
            if addr == "::1":
                return True
        except Exception:
            pass
    return False


def _validate_base_url(base_url: str) -> str:
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        raise LocalhostOnlyError("base_url_missing")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise LocalhostOnlyError("base_url_invalid_scheme")
    host = parsed.hostname or ""
    if not _is_loopback_host(host):
        raise LocalhostOnlyError(f"base_url_not_loopback:{host}")
    return raw


def _request_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    timeout_s: float,
    headers: dict[str, str] | None = None,
    max_response_bytes: int = 10_000_000,
) -> dict[str, Any]:
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **(headers or {}),
    }
    with _maybe_managed_vlm_gate(url=url, timeout_s=float(timeout_s)):
        out = request_json(
            method=str(method or "POST").upper(),
            url=str(url),
            payload=payload,
            timeout_s=float(timeout_s),
            headers=request_headers,
        )
    if not bool(out.get("ok", False)):
        status = int(out.get("status", 0) or 0)
        if status >= 400:
            raise RuntimeError(f"http_error:{status}:{out.get('payload')!r}")
        raise RuntimeError(f"http_failed:{out.get('error')}")
    parsed = out.get("payload", {})
    blob = json.dumps(parsed, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(blob) > int(max_response_bytes):
        raise RuntimeError("response_too_large")
    return parsed if isinstance(parsed, dict) else {"data": parsed}


@dataclass(frozen=True)
class OpenAICompatClient:
    base_url: str
    api_key: str | None = None
    timeout_s: float = 20.0
    max_response_bytes: int = 20_000_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _validate_base_url(self.base_url))

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _endpoint_url(self, suffix: str) -> str:
        base = self.base_url.rstrip("/")
        part = str(suffix or "")
        if not part.startswith("/"):
            part = "/" + part
        if base.endswith("/v1") and part.startswith("/v1/"):
            return f"{base}{part[3:]}"
        return f"{base}{part}"

    def list_models(self) -> dict[str, Any]:
        url = self._endpoint_url("/v1/models")
        return _request_json(
            method="GET",
            url=url,
            payload=None,
            timeout_s=self.timeout_s,
            headers=self._headers(),
            max_response_bytes=self.max_response_bytes,
        )

    def chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._endpoint_url("/v1/chat/completions")
        return _request_json(
            method="POST",
            url=url,
            payload=payload,
            timeout_s=self.timeout_s,
            headers=self._headers(),
            max_response_bytes=self.max_response_bytes,
        )

    def embeddings(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._endpoint_url("/v1/embeddings")
        return _request_json(
            method="POST",
            url=url,
            payload=payload,
            timeout_s=self.timeout_s,
            headers=self._headers(),
            max_response_bytes=self.max_response_bytes,
        )


def image_bytes_to_data_url(image_bytes: bytes, *, content_type: str = "image/png") -> str:
    """Encode bytes as a data: URL for OpenAI-compatible image inputs."""
    blob = bytes(image_bytes or b"")
    b64 = base64.b64encode(blob).decode("ascii")
    return f"data:{content_type};base64,{b64}"
