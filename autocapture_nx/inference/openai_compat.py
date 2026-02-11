"""Localhost-only OpenAI-compatible client helpers.

This is used for talking to local inference servers (eg vLLM) on 127.0.0.1.
It must never be used for non-loopback egress.
"""

from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class LocalhostOnlyError(RuntimeError):
    pass


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
        try:
            if socket.inet_pton(socket.AF_INET, addr):
                if addr.startswith("127."):
                    return True
        except Exception:
            pass
        try:
            if socket.inet_pton(socket.AF_INET6, addr):
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
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        method=str(method or "POST").upper(),
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            data = resp.read(int(max_response_bytes) + 1)
    except urllib.error.HTTPError as exc:
        try:
            blob = exc.read(4096)
        except Exception:
            blob = b""
        raise RuntimeError(f"http_error:{exc.code}:{blob[:256]!r}") from exc
    except Exception as exc:
        raise RuntimeError(f"http_failed:{type(exc).__name__}:{exc}") from exc
    if len(data) > int(max_response_bytes):
        raise RuntimeError("response_too_large")
    try:
        parsed = json.loads(data.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise RuntimeError(f"invalid_json:{exc}") from exc
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

    def list_models(self) -> dict[str, Any]:
        url = f"{self.base_url}/v1/models"
        return _request_json(
            method="GET",
            url=url,
            payload=None,
            timeout_s=self.timeout_s,
            headers=self._headers(),
            max_response_bytes=self.max_response_bytes,
        )

    def chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        return _request_json(
            method="POST",
            url=url,
            payload=payload,
            timeout_s=self.timeout_s,
            headers=self._headers(),
            max_response_bytes=self.max_response_bytes,
        )

    def embeddings(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/v1/embeddings"
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

