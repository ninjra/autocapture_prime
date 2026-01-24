"""Egress gateway plugin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.config import SchemaLiteValidator
from autocapture_nx.kernel.errors import ConfigError

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

    def send(self, payload: dict[str, Any], provider: str = "default") -> dict[str, Any]:
        privacy = self.context.config.get("privacy", {})
        egress_cfg = privacy.get("egress", {})
        cloud_cfg = privacy.get("cloud", {})

        if not egress_cfg.get("enabled", True):
            raise NetworkDisabledError("Egress is disabled by config")
        if not cloud_cfg.get("enabled", False):
            raise NetworkDisabledError("Cloud usage is disabled by config")

        sanitizer = self.context.get_capability("privacy.egress_sanitizer")
        sanitized = payload
        if egress_cfg.get("default_sanitize", True):
            sanitized = sanitizer.sanitize_payload(payload, scope=provider)
            if not sanitizer.leak_check(sanitized):
                raise PermissionError("Egress sanitizer leak check failed")
        elif not egress_cfg.get("allow_raw_egress", False):
            raise PermissionError("Raw egress not allowed by policy")

        reasoning_only = egress_cfg.get("reasoning_packet_only", True)
        if reasoning_only:
            sanitized = self._build_reasoning_packet(payload, sanitized)
            try:
                self._validator.validate(self._load_schema(), sanitized)
            except ConfigError as exc:
                raise PermissionError(f"Reasoning packet schema violation: {exc}") from exc

        # No real network I/O in baseline; return a stub response.
        response = {"status": "blocked_local", "payload": sanitized}
        return response

    def detokenize(self, payload: dict[str, Any]) -> dict[str, Any]:
        sanitizer = self.context.get_capability("privacy.egress_sanitizer")
        return sanitizer.detokenize_payload(payload)


def create_plugin(plugin_id: str, context: PluginContext) -> EgressGateway:
    return EgressGateway(plugin_id, context)
