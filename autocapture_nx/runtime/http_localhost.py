"""HTTP JSON helpers with localhost curl fallback for sandboxed runtimes."""

from __future__ import annotations

import json
import math
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _is_localhost_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(url))
    except Exception:
        return False
    host = str(parsed.hostname or "").strip().lower()
    return host in {"127.0.0.1", "localhost"}


def _should_try_curl(url: str, exc: Exception) -> bool:
    force = str(os.environ.get("AUTOCAPTURE_HTTP_LOCALHOST_FORCE_CURL") or "").strip().casefold()
    if force in {"1", "true", "yes", "on"} and _is_localhost_url(url):
        return True
    if not _is_localhost_url(url):
        return False
    text = f"{type(exc).__name__}:{exc}"
    lowered = text.casefold()
    return ("operation not permitted" in lowered) or ("errno 1" in lowered)


def _json_or_empty(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
        return {"raw": payload}
    except Exception:
        return {}


def _curl_json_request(
    *,
    method: str,
    url: str,
    timeout_s: float,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    timeout = max(1, int(math.ceil(float(timeout_s))))
    cmd: list[str] = ["curl", "-sS", "--max-time", str(timeout), "-X", str(method).upper()]
    for key, value in (headers or {}).items():
        cmd.extend(["-H", f"{key}: {value}"])
    if payload is not None:
        cmd.extend(["-H", "Content-Type: application/json", "--data", json.dumps(payload, sort_keys=True)])
    cmd.extend([str(url), "-w", "\n__STATUS__:%{http_code}"])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if int(proc.returncode) != 0:
        return {
            "ok": False,
            "status": 0,
            "payload": {},
            "error": f"curl_failed:rc={int(proc.returncode)}:{str(proc.stderr or '').strip()}",
            "transport": "curl",
        }
    stdout = str(proc.stdout or "")
    marker = "\n__STATUS__:"
    idx = stdout.rfind(marker)
    if idx < 0:
        return {
            "ok": False,
            "status": 0,
            "payload": {},
            "error": "curl_failed:missing_status_marker",
            "transport": "curl",
        }
    body = stdout[:idx]
    status_text = stdout[idx + len(marker) :].strip()
    try:
        status = int(status_text or "0")
    except Exception:
        status = 0
    parsed = _json_or_empty(body)
    if 200 <= status < 300:
        return {"ok": True, "status": status, "payload": parsed, "error": "", "transport": "curl"}
    return {
        "ok": False,
        "status": status,
        "payload": parsed,
        "error": f"http_error:{status}",
        "transport": "curl",
    }


def request_json(
    *,
    method: str,
    url: str,
    timeout_s: float,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = None
    req_headers = dict(headers or {})
    if payload is not None:
        req_headers.setdefault("Content-Type", "application/json")
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
    req = urllib.request.Request(url=str(url), data=data, method=str(method).upper(), headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            body = resp.read() or b"{}"
            parsed = _json_or_empty(body.decode("utf-8", errors="replace"))
            return {
                "ok": True,
                "status": int(getattr(resp, "status", 0)),
                "payload": parsed,
                "error": "",
                "transport": "urllib",
            }
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            raw = exc.read()
            if raw:
                body = raw.decode("utf-8", errors="replace")
        except Exception:
            body = ""
        status = int(getattr(exc, "code", 0) or 0)
        return {
            "ok": False,
            "status": status,
            "payload": _json_or_empty(body),
            "error": f"http_error:{status}",
            "transport": "urllib",
        }
    except Exception as exc:
        if _should_try_curl(url, exc):
            return _curl_json_request(
                method=method,
                url=url,
                timeout_s=timeout_s,
                payload=payload,
                headers=headers,
            )
        return {
            "ok": False,
            "status": 0,
            "payload": {},
            "error": f"{type(exc).__name__}:{exc}",
            "transport": "urllib",
        }

