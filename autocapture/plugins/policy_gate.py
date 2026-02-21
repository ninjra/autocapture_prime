"""Policy gate for network egress enforcement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from autocapture_nx.kernel.egress_approvals import EgressApprovalStore
from autocapture_nx.kernel.hashing import sha256_canonical, sha256_text


class PolicyError(RuntimeError):
    """Raised when policy gate blocks an action."""


@dataclass(frozen=True)
class PolicyDecision:
    ok: bool
    reason: str
    sanitized_payload: dict[str, Any] | None = None
    packet_hash: str | None = None
    policy_id: str | None = None
    approval_id: str | None = None


class PolicyGate:
    def __init__(
        self,
        config: dict[str, Any],
        sanitizer: Any | None,
        *,
        approval_store: Any | None = None,
        event_builder: Any | None = None,
    ) -> None:
        self.config = config
        self.sanitizer = sanitizer
        self._approval_store = approval_store
        self._event_builder = event_builder

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

    def _egress_cfg(self) -> dict[str, Any]:
        privacy = self.config.get("privacy", {})
        egress = privacy.get("egress", {}) if isinstance(privacy, dict) else {}
        return egress if isinstance(egress, dict) else {}

    def _cloud_cfg(self) -> dict[str, Any]:
        privacy = self.config.get("privacy", {})
        cloud = privacy.get("cloud", {}) if isinstance(privacy, dict) else {}
        return cloud if isinstance(cloud, dict) else {}

    def _dest_allowlist(self) -> list[str]:
        egress = self._egress_cfg()
        raw = egress.get("destination_allowlist", [])
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        return []

    def _dest_allowed(self, url: str) -> bool:
        allow = self._dest_allowlist()
        if not allow:
            return False
        parsed = urlparse(str(url))
        host = (parsed.netloc or parsed.hostname or "").lower()
        full = str(url)
        for item in allow:
            token = str(item).strip()
            if not token:
                continue
            if "://" in token:
                # URL prefix allowlist.
                if full.startswith(token):
                    return True
                continue
            t = token.lower()
            if t.startswith("*."):
                suffix = t[1:]  # keep leading dot
                if host.endswith(suffix):
                    return True
                continue
            if host == t:
                return True
            if host.endswith("." + t):
                return True
        return False

    def _policy_id(self, url: str) -> str:
        egress = self._egress_cfg()
        raw = str(egress.get("policy_id") or egress.get("destination_policy_id") or "").strip()
        if raw:
            return raw
        parsed = urlparse(str(url))
        host = (parsed.netloc or parsed.hostname or "").lower()
        path = parsed.path or ""
        return sha256_text(f"{host}:{path}")

    def _emit_ledger(self, event: str, payload: dict[str, Any]) -> None:
        builder = self._event_builder
        if builder is None:
            return
        try:
            builder.ledger_entry("egress.policy", inputs=[], outputs=[], payload={"event": event, **payload})
        except Exception:
            return

    def enforce(
        self,
        plugin_id: str,
        payload: dict[str, Any],
        *,
        url: str | None = None,
        allow_raw_egress: bool = False,
        allow_images: bool = False,
    ) -> PolicyDecision:
        if self._safe_mode():
            return PolicyDecision(ok=False, reason="safe_mode_block")

        if plugin_id not in self._network_allowlist():
            return PolicyDecision(ok=False, reason="plugin_not_allowlisted")

        cloud = self._cloud_cfg()
        egress = self._egress_cfg()

        if not egress.get("enabled", True):
            return PolicyDecision(ok=False, reason="egress_disabled")

        if not cloud.get("enabled", False):
            return PolicyDecision(ok=False, reason="cloud_disabled")

        dest_url = str(url or "").strip()
        if dest_url:
            if not self._dest_allowed(dest_url):
                return PolicyDecision(ok=False, reason="destination_not_allowlisted")

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

        # Approval tokens must not affect packet hashing; otherwise the act of
        # supplying a token changes the packet_hash and invalidates approval.
        hashed_payload = dict(sanitized) if isinstance(sanitized, dict) else {}
        hashed_payload.pop("approval_token", None)
        hashed_payload.pop("_approval_token", None)
        packet_hash = sha256_canonical(hashed_payload)
        policy_id = self._policy_id(dest_url) if dest_url else (str(egress.get("policy_id") or "") or "")

        approval_required = bool(egress.get("approval_required", True))
        approval_id = None
        if approval_required:
            store = self._approval_store
            if store is None:
                store = EgressApprovalStore(self.config, self._event_builder)
                self._approval_store = store
            token = payload.get("approval_token") or payload.get("_approval_token")
            if token:
                approval_id = store.verify(str(token), packet_hash, str(policy_id))
                if not approval_id:
                    self._emit_ledger(
                        "egress.blocked",
                        {"plugin_id": plugin_id, "reason": "approval_invalid", "packet_hash": packet_hash, "policy_id": policy_id},
                    )
                    return PolicyDecision(ok=False, reason="approval_invalid", sanitized_payload=sanitized, packet_hash=packet_hash, policy_id=policy_id)
            else:
                req = store.request(packet_hash, str(policy_id), int(sanitized.get("schema_version", 1) or 1))
                approval_id = req.get("approval_id") if isinstance(req, dict) else None
                self._emit_ledger(
                    "egress.blocked",
                    {"plugin_id": plugin_id, "reason": "approval_required", "packet_hash": packet_hash, "policy_id": policy_id, "approval_id": approval_id},
                )
                reason = f"approval_required:{approval_id}" if approval_id else "approval_required"
                return PolicyDecision(ok=False, reason=reason, sanitized_payload=sanitized, packet_hash=packet_hash, policy_id=policy_id, approval_id=approval_id)

        self._emit_ledger(
            "egress.allowed",
            {"plugin_id": plugin_id, "packet_hash": packet_hash, "policy_id": policy_id, "approval_id": approval_id},
        )
        return PolicyDecision(ok=True, reason="sanitized", sanitized_payload=sanitized, packet_hash=packet_hash, policy_id=policy_id, approval_id=approval_id)
