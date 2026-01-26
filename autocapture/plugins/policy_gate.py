"""Policy gate for network egress enforcement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


class PolicyError(RuntimeError):
    """Raised when policy gate blocks an action."""


@dataclass(frozen=True)
class PolicyDecision:
    ok: bool
    reason: str
    sanitized_payload: dict[str, Any] | None = None


class PolicyGate:
    def __init__(self, config: dict[str, Any], sanitizer: Any | None) -> None:
        self.config = config
        self.sanitizer = sanitizer

    def _safe_mode(self) -> bool:
        if os.getenv("AUTOCAPTURE_SAFE_MODE") in {"1", "true", "yes"}:
            return True
        return bool(self.config.get("plugins", {}).get("safe_mode", False))

    def _network_allowlist(self) -> set[str]:
        return set(
            self.config.get("plugins", {})
            .get("permissions", {})
            .get("network_allowed_plugin_ids", [])
        )

    def enforce(
        self,
        plugin_id: str,
        payload: dict[str, Any],
        *,
        allow_raw_egress: bool = False,
        allow_images: bool = False,
    ) -> PolicyDecision:
        if self._safe_mode():
            return PolicyDecision(ok=False, reason="safe_mode_block")

        if plugin_id not in self._network_allowlist():
            return PolicyDecision(ok=False, reason="plugin_not_allowlisted")

        privacy = self.config.get("privacy", {})
        cloud = privacy.get("cloud", {})
        egress = privacy.get("egress", {})

        if not cloud.get("enabled", False):
            return PolicyDecision(ok=False, reason="cloud_disabled")

        if allow_images and not cloud.get("allow_images", False):
            return PolicyDecision(ok=False, reason="cloud_images_blocked")

        if allow_raw_egress:
            if not egress.get("allow_raw_egress", False):
                return PolicyDecision(ok=False, reason="raw_egress_blocked")
            return PolicyDecision(ok=True, reason="raw_egress_allowed", sanitized_payload=payload)

        if not egress.get("default_sanitize", False):
            return PolicyDecision(ok=False, reason="sanitize_required")

        if self.sanitizer is None:
            return PolicyDecision(ok=False, reason="sanitizer_missing")

        sanitized = self.sanitizer.sanitize_payload(payload)
        leak_ok = self.sanitizer.leak_check(sanitized)
        if not leak_ok:
            return PolicyDecision(ok=False, reason="sanitizer_leak_detected")

        return PolicyDecision(ok=True, reason="sanitized", sanitized_payload=sanitized)
