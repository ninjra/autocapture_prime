"""Egress approval store for outbound packet approvals."""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    created_ts: str
    packet_hash: str
    policy_id: str
    schema_version: int


@dataclass(frozen=True)
class ApprovalToken:
    token: str
    approval_id: str
    packet_hash: str
    policy_id: str
    expires_ts: str


class EgressApprovalStore:
    def __init__(self, config: dict[str, Any], event_builder: Any | None = None) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, ApprovalRequest] = {}
        self._approved: dict[str, ApprovalToken] = {}
        self._event_builder = event_builder
        privacy = config.get("privacy", {}) if isinstance(config, dict) else {}
        egress_cfg = privacy.get("egress", {}) if isinstance(privacy, dict) else {}
        data_dir = config.get("storage", {}).get("data_dir", "data") if isinstance(config, dict) else "data"
        self._ttl_s = float(egress_cfg.get("approval_ttl_s", 300))
        self._path = str(egress_cfg.get("approval_store_path") or os.path.join(data_dir, "egress", "approvals.json"))
        self._load()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._event_builder is None:
            return
        try:
            self._event_builder.ledger_entry("egress.approval", inputs=[], outputs=[], payload={"event": event, **payload})
        except Exception:
            return

    def _load(self) -> None:
        if not self._path or not os.path.exists(self._path):
            return
        try:
            payload = json.loads(open(self._path, "r", encoding="utf-8").read())
        except Exception:
            return
        pending = payload.get("pending", []) if isinstance(payload, dict) else []
        approved = payload.get("approved", []) if isinstance(payload, dict) else []
        for item in pending:
            if not isinstance(item, dict):
                continue
            try:
                req = ApprovalRequest(
                    approval_id=str(item.get("approval_id")),
                    created_ts=str(item.get("created_ts")),
                    packet_hash=str(item.get("packet_hash")),
                    policy_id=str(item.get("policy_id")),
                    schema_version=int(item.get("schema_version", 1)),
                )
            except Exception:
                continue
            if req.approval_id:
                self._pending[req.approval_id] = req
        for item in approved:
            if not isinstance(item, dict):
                continue
            try:
                token = ApprovalToken(
                    token=str(item.get("token")),
                    approval_id=str(item.get("approval_id")),
                    packet_hash=str(item.get("packet_hash")),
                    policy_id=str(item.get("policy_id")),
                    expires_ts=str(item.get("expires_ts")),
                )
            except Exception:
                continue
            if token.token:
                self._approved[token.token] = token

    def _save(self) -> None:
        if not self._path:
            return
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        payload = {
            "pending": [asdict(req) for req in self._pending.values()],
            "approved": [asdict(tok) for tok in self._approved.values()],
        }
        with open(self._path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

    def _expire_tokens(self) -> None:
        now = self._now()
        expired = []
        for token, record in self._approved.items():
            try:
                expires = datetime.fromisoformat(record.expires_ts)
            except Exception:
                expires = now
            if expires <= now:
                expired.append(token)
        for token in expired:
            self._approved.pop(token, None)

    def request(self, packet_hash: str, policy_id: str, schema_version: int) -> dict[str, Any]:
        approval_id = str(uuid.uuid4())
        created_ts = self._now().isoformat()
        req = ApprovalRequest(
            approval_id=approval_id,
            created_ts=created_ts,
            packet_hash=packet_hash,
            policy_id=policy_id,
            schema_version=int(schema_version or 1),
        )
        with self._lock:
            self._pending[approval_id] = req
            self._save()
        self._emit("egress.approval.request", asdict(req))
        return asdict(req)

    def list_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(req) for req in self._pending.values()]

    def approve(self, approval_id: str, ttl_s: float | None = None) -> dict[str, Any]:
        with self._lock:
            req = self._pending.pop(approval_id, None)
            if req is None:
                raise KeyError("approval_request_missing")
            ttl = float(ttl_s) if ttl_s is not None else self._ttl_s
            expires = self._now() + timedelta(seconds=max(1.0, ttl))
            token = ApprovalToken(
                token=str(uuid.uuid4()),
                approval_id=req.approval_id,
                packet_hash=req.packet_hash,
                policy_id=req.policy_id,
                expires_ts=expires.isoformat(),
            )
            self._approved[token.token] = token
            self._save()
        payload = asdict(token)
        self._emit("egress.approval.granted", payload)
        return payload

    def deny(self, approval_id: str) -> None:
        with self._lock:
            req = self._pending.pop(approval_id, None)
            self._save()
        if req is not None:
            self._emit("egress.approval.denied", asdict(req))

    def verify(self, token: str, packet_hash: str, policy_id: str) -> str | None:
        if not token:
            return None
        with self._lock:
            self._expire_tokens()
            record = self._approved.get(token)
            if record is None:
                return None
            if record.packet_hash != packet_hash:
                return None
            if record.policy_id != policy_id:
                return None
            return record.approval_id

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._expire_tokens()
            return {
                "pending": len(self._pending),
                "approved": len(self._approved),
            }
