"""Policy gate for state-layer retrieval and evidence export."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StatePolicyDecision:
    can_show_raw_media: bool
    can_export_text: bool
    redact_text: bool
    app_allowlist: tuple[str, ...]
    app_denylist: tuple[str, ...]


class StatePolicyGate:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config if isinstance(config, dict) else {}

    def _policy_cfg(self) -> dict[str, Any]:
        processing = self._config.get("processing", {}) if isinstance(self._config, dict) else {}
        state_cfg = processing.get("state_layer", {}) if isinstance(processing, dict) else {}
        policy_cfg = state_cfg.get("policy", {}) if isinstance(state_cfg, dict) else {}
        return policy_cfg if isinstance(policy_cfg, dict) else {}

    def decide(self, _query_context: dict[str, Any] | None = None) -> StatePolicyDecision:
        cfg = self._policy_cfg()
        allow_media = bool(cfg.get("allow_raw_media", False))
        allow_text = bool(cfg.get("allow_text_export", True))
        redact_text = bool(cfg.get("redact_text", False))
        allowlist = tuple(str(item).lower() for item in cfg.get("app_allowlist", []) if item)
        denylist = tuple(str(item).lower() for item in cfg.get("app_denylist", []) if item)
        return StatePolicyDecision(
            can_show_raw_media=allow_media,
            can_export_text=allow_text,
            redact_text=redact_text,
            app_allowlist=allowlist,
            app_denylist=denylist,
        )

    def app_allowed(self, app_hint: str | None, decision: StatePolicyDecision | None = None) -> bool:
        if decision is None:
            decision = self.decide()
        if not app_hint:
            return True
        needle = str(app_hint).lower()
        if decision.app_allowlist:
            return any(token in needle for token in decision.app_allowlist)
        if decision.app_denylist:
            return not any(token in needle for token in decision.app_denylist)
        return True
