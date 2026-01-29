"""Egress gateway plugin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import urllib.request

try:
    import httpx
except Exception:  # pragma: no cover - optional dependency
    httpx = None  # type: ignore[assignment]

from autocapture_nx.kernel.config import SchemaLiteValidator
from autocapture_nx.kernel.errors import ConfigError
from autocapture_nx.kernel.hashing import sha256_canonical, sha256_text

from autocapture.plugins.policy_gate import PolicyGate
from autocapture_nx.kernel.errors import NetworkDisabledError, PermissionError
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class EgressGateway(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._validator = SchemaLiteValidator()
        self._schema = None

    def capabilities(self) -> dict[str, Any]:
        return {"egress.gateway": self}

    def _load_schema(self) -> dict[str, Any]:
        if self._schema is not None:
            return self._schema
        schema_path = Path("contracts") / "reasoning_packet.schema.json"
        with schema_path.open("r", encoding="utf-8") as handle:
            self._schema = json.load(handle)
        return self._schema

    def _build_reasoning_packet(self, payload: dict[str, Any], sanitized: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "query_sanitized": sanitized.get("query", payload.get("query", "")),
            "facts": sanitized.get("facts", payload.get("facts", [])),
            "constraints": sanitized.get("constraints", payload.get("constraints", {})),
            "time_window": sanitized.get("time_window", payload.get("time_window")),
            "intent": sanitized.get("intent", payload.get("intent", "")),
            "output_contract": payload.get("output_contract", {}),
            "entity_glossary": sanitized.get("_glossary", []),
            "token_map": sanitized.get("_tokens", {}),
            "citations_stub": payload.get("citations_stub", []),
        }

    def _endpoint(self) -> tuple[str, dict[str, str], float]:
        gateway_cfg = self.context.config.get("gateway", {}) if isinstance(self.context.config, dict) else {}
        base_url = str(gateway_cfg.get("openai_base_url", "")).strip()
        if not base_url:
            raise ConfigError("gateway_base_url_missing")
        path = str(gateway_cfg.get("egress_path", "/v1/egress")).strip() or "/v1/egress"
        if not path.startswith("/"):
            path = f"/{path}"
        url = base_url.rstrip("/") + path
        headers: dict[str, str] = {"Content-Type": "application/json"}
        api_key = str(gateway_cfg.get("openai_api_key", "")).strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        timeout_s = float(gateway_cfg.get("timeout_s", 30.0))
        return url, headers, timeout_s

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float) -> tuple[int, Any]:
        if httpx is not None:
            resp = httpx.post(url, json=payload, headers=headers, timeout=timeout_s)  # type: ignore[union-attr]
            try:
                return resp.status_code, resp.json()
            except Exception:
                return resp.status_code, {"text": resp.text}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.getcode(), json.loads(body) if body else {}
            except Exception:
                return resp.getcode(), {"text": body}

    def _policy_id(self) -> str:
        privacy = self.context.config.get("privacy", {}) if isinstance(self.context.config, dict) else {}
        egress_cfg = privacy.get("egress", {}) if isinstance(privacy, dict) else {}
        raw = str(egress_cfg.get("policy_id") or egress_cfg.get("destination_policy_id") or "").strip()
        if raw:
            return raw
        base = self.context.config.get("gateway", {}).get("openai_base_url", "")
        path = self.context.config.get("gateway", {}).get("egress_path", "/v1/egress")
        return sha256_text(f"{base}:{path}")

    def _packet_hash(self, payload: dict[str, Any]) -> str:
        return sha256_canonical(payload)

    def _ledger_packet(
        self,
        packet_hash: str | None,
        schema_version: int | None,
        *,
        policy_id: str,
        approval_id: str | None,
        result: str,
        reason: str | None = None,
    ) -> None:
        try:
            builder = self.context.get_capability("event.builder")
        except Exception:
            builder = None
        if builder is None:
            return
        payload: dict[str, Any] = {
            "event": "egress.packet",
            "policy_id": policy_id,
            "result": result,
        }
        if packet_hash is not None:
            payload["packet_hash"] = packet_hash
        if schema_version is not None:
            payload["schema_version"] = int(schema_version)
        if approval_id:
            payload["approval_id"] = approval_id
        if reason:
            payload["reason"] = reason
        builder.ledger_entry("egress.packet", inputs=[], outputs=[], payload=payload)

    def _approval_store(self):
        try:
            return self.context.get_capability("egress.approval_store")
        except Exception:
            return None

    def send(self, payload: dict[str, Any], provider: str = "default", approval_token: str | None = None) -> dict[str, Any]:
        _ = provider
        privacy = self.context.config.get("privacy", {}) if isinstance(self.context.config, dict) else {}
        egress_cfg = privacy.get("egress", {})

        if not egress_cfg.get("enabled", True):
            raise NetworkDisabledError("Egress is disabled by config")

        sanitizer = self.context.get_capability("privacy.egress_sanitizer")
        gate = PolicyGate(self.context.config, sanitizer)
        allow_images = bool(payload.get("allow_images", False) or payload.get("images"))
        decision = gate.enforce(self.plugin_id, payload, allow_raw_egress=False, allow_images=allow_images)
        if not decision.ok:
            self._ledger_packet(
                packet_hash=None,
                schema_version=None,
                policy_id=self._policy_id(),
                approval_id=None,
                result="blocked",
                reason=decision.reason,
            )
            raise PermissionError(decision.reason)
        sanitized = decision.sanitized_payload or payload

        reasoning_only = egress_cfg.get("reasoning_packet_only", True)
        if reasoning_only:
            sanitized = self._build_reasoning_packet(payload, sanitized)
            try:
                self._validator.validate(self._load_schema(), sanitized)
            except ConfigError as exc:
                self._ledger_packet(
                    packet_hash=None,
                    schema_version=None,
                    policy_id=self._policy_id(),
                    approval_id=None,
                    result="blocked",
                    reason=str(exc),
                )
                raise PermissionError(f"Reasoning packet schema violation: {exc}") from exc

        packet_hash = self._packet_hash(sanitized)
        policy_id = self._policy_id()
        schema_version = int(sanitized.get("schema_version", 1) or 1)
        approval_required = bool(egress_cfg.get("approval_required", False))
        approval_id = None
        if approval_required:
            token = approval_token or payload.get("approval_token") or payload.get("_approval_token")
            store = self._approval_store()
            if store is None:
                self._ledger_packet(
                    packet_hash=packet_hash,
                    schema_version=schema_version,
                    policy_id=policy_id,
                    approval_id=None,
                    result="blocked",
                    reason="approval_store_missing",
                )
                raise PermissionError("approval_store_missing")
            if token:
                approval_id = store.verify(token, packet_hash, policy_id)
                if not approval_id:
                    self._ledger_packet(
                        packet_hash=packet_hash,
                        schema_version=schema_version,
                        policy_id=policy_id,
                        approval_id=None,
                        result="blocked",
                        reason="approval_invalid",
                    )
                    raise PermissionError("approval_invalid")
            else:
                approval = store.request(packet_hash, policy_id, schema_version)
                approval_id = approval.get("approval_id") if isinstance(approval, dict) else None
                self._ledger_packet(
                    packet_hash=packet_hash,
                    schema_version=schema_version,
                    policy_id=policy_id,
                    approval_id=approval_id,
                    result="blocked",
                    reason="approval_required",
                )
                raise PermissionError(f"approval_required:{approval_id}" if approval_id else "approval_required")

        url, headers, timeout_s = self._endpoint()
        status_code, response_payload = self._post_json(url, sanitized, headers, timeout_s)
        self._ledger_packet(
            packet_hash=packet_hash,
            schema_version=schema_version,
            policy_id=policy_id,
            approval_id=approval_id,
            result="sent" if 200 <= status_code < 300 else "error",
        )
        return {
            "status": "ok" if 200 <= status_code < 300 else "error",
            "status_code": status_code,
            "payload": sanitized,
            "response": response_payload,
            "packet_hash": packet_hash,
            "policy_id": policy_id,
            "approval_id": approval_id,
        }

    def detokenize(self, payload: dict[str, Any]) -> dict[str, Any]:
        sanitizer = self.context.get_capability("privacy.egress_sanitizer")
        return sanitizer.detokenize_payload(payload)


def create_plugin(plugin_id: str, context: PluginContext) -> EgressGateway:
    return EgressGateway(plugin_id, context)
