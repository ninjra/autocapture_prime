"""Anchor writer plugin for ledger head hashes."""

from __future__ import annotations

import base64
import os
import errno
import hmac
import hashlib
import tempfile
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.crypto import derive_key
from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class AnchorWriter(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        storage_cfg = context.config.get("storage", {})
        anchor_cfg = storage_cfg.get("anchor", {})
        self._path = anchor_cfg.get("path", os.path.join("anchor", "anchors.ndjson"))
        self._use_dpapi = bool(anchor_cfg.get("use_dpapi", os.name == "nt"))
        self._sign = bool(anchor_cfg.get("sign", True))
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._seq = 0
        self._keyring: KeyRing | None = None
        self._load_seq()

    def _is_perm_error(self, exc: BaseException) -> bool:
        if isinstance(exc, PermissionError):
            return True
        if isinstance(exc, OSError):
            return exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS)
        return False

    def _fallback_path(self) -> str:
        digest = hashlib.sha256(self._path.encode("utf-8")).hexdigest()[:16]
        root = os.path.join(tempfile.gettempdir(), "autocapture", "shadow_logs")
        os.makedirs(root, exist_ok=True)
        return os.path.join(root, f"{digest}.anchors.ndjson")

    def _use_fallback_path(self) -> None:
        fallback = self._fallback_path()
        if fallback != self._path:
            self._path = fallback

    def _load_seq(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    self._seq += 1
        except Exception as exc:
            if self._is_perm_error(exc):
                self._use_fallback_path()
                return
            raise

    def capabilities(self) -> dict[str, Any]:
        return {"anchor.writer": self}

    def anchor(self, ledger_head_hash: str) -> dict[str, Any]:
        record: dict[str, Any] = {
            "record_type": "system.anchor",
            "schema_version": 1,
            "anchor_seq": self._seq,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "ledger_head_hash": ledger_head_hash,
        }
        if self._sign:
            key_info = self._signing_key()
            if key_info is not None:
                key_id, key = key_info
                payload = dumps(record).encode("utf-8")
                record["anchor_key_id"] = key_id
                record["anchor_hmac"] = hmac.new(key, payload, hashlib.sha256).hexdigest()
        payload = dumps(record).encode("utf-8")
        if self._use_dpapi and os.name == "nt":
            try:
                from autocapture_nx.windows.dpapi import protect

                payload = protect(payload)
                payload = b"DPAPI:" + base64.b64encode(payload)
            except Exception:
                payload = dumps(record).encode("utf-8")
        try:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(payload.decode("utf-8") + "\n")
        except Exception as exc:
            if not self._is_perm_error(exc):
                raise
            self._use_fallback_path()
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(payload.decode("utf-8") + "\n")
        self._seq += 1
        return record

    def _signing_key(self) -> tuple[str, bytes] | None:
        if not self._sign:
            return None
        if self._keyring is None:
            try:
                self._keyring = self.context.get_capability("storage.keyring")
            except Exception:
                self._keyring = None
        if self._keyring is None:
            return None
        try:
            key_id, root = self._keyring.active_key("anchor")
        except Exception as exc:
            # Fail-open for anchoring availability on non-Windows hosts where
            # imported key material may be DPAPI-protected by the sidecar.
            self._sign = False
            try:
                self.context.logger(f"anchor signing disabled: {type(exc).__name__}: {exc}")
            except Exception:
                pass
            return None
        return key_id, derive_key(root, "anchor")


def create_plugin(plugin_id: str, context: PluginContext) -> AnchorWriter:
    return AnchorWriter(plugin_id, context)
