"""Network egress client that enforces PolicyGate."""

from __future__ import annotations

from typing import Any

import json
import urllib.request

try:
    import httpx
except Exception:  # pragma: no cover - optional dependency
    httpx = None  # type: ignore[assignment]

from autocapture.plugins.policy_gate import PolicyGate, PolicyError


class _SimpleResponse:
    def __init__(self, status_code: int, content: str) -> None:
        self.status_code = status_code
        self._content = content

    def json(self) -> Any:
        if not self._content:
            return {}
        return json.loads(self._content)

    @property
    def text(self) -> str:
        return self._content


class EgressClient:
    def __init__(self, policy_gate: PolicyGate, timeout_s: float = 30.0) -> None:
        self.policy_gate = policy_gate
        self.timeout_s = timeout_s

    def request(
        self,
        method: str,
        url: str,
        *,
        plugin_id: str,
        payload: dict[str, Any] | None = None,
        allow_raw_egress: bool = False,
        allow_images: bool = False,
    ) -> Any:
        payload = payload or {}
        decision = self.policy_gate.enforce(
            plugin_id,
            payload,
            allow_raw_egress=allow_raw_egress,
            allow_images=allow_images,
        )
        if not decision.ok:
            raise PolicyError(decision.reason)
        data = decision.sanitized_payload or payload
        if httpx is not None:
            with httpx.Client(timeout=self.timeout_s) as client:  # type: ignore[union-attr]
                return client.request(method, url, json=data)
        payload_bytes = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload_bytes,
            method=method.upper(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            body = resp.read().decode("utf-8")
            return _SimpleResponse(resp.getcode(), body)

    def post(self, url: str, *, plugin_id: str, payload: dict[str, Any] | None = None, allow_raw_egress: bool = False, allow_images: bool = False) -> Any:
        return self.request(
            "POST",
            url,
            plugin_id=plugin_id,
            payload=payload,
            allow_raw_egress=allow_raw_egress,
            allow_images=allow_images,
        )

    def get(self, url: str, *, plugin_id: str) -> Any:
        return self.request("GET", url, plugin_id=plugin_id, payload={})
