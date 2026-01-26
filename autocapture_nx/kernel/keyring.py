"""Keyring management for root keys with rotation."""

from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from autocapture_nx.kernel.crypto import load_root_key


def _new_id() -> str:
    if hasattr(uuid, "uuid7"):
        return str(uuid.uuid7())  # type: ignore[attr-defined]
    return str(uuid.uuid4())


def _protect(data: bytes) -> tuple[bytes, bool]:
    if os.name != "nt":
        return data, False
    try:
        from autocapture_nx.windows.dpapi import protect

        return protect(data), True
    except Exception:
        return data, False


def _unprotect(data: bytes, protected: bool) -> bytes:
    if not protected:
        return data
    if os.name != "nt":
        raise RuntimeError("DPAPI unprotect requires Windows")
    try:
        from autocapture_nx.windows.dpapi import unprotect

        return unprotect(data)
    except Exception as exc:
        raise RuntimeError("DPAPI unprotect failed") from exc


@dataclass
class KeyRecord:
    key_id: str
    created_ts: str
    key_b64: str
    protected: bool

    def key_bytes(self) -> bytes:
        raw = base64.b64decode(self.key_b64)
        return _unprotect(raw, self.protected)


class KeyRing:
    def __init__(self, path: str, active_key_id: str, records: list[KeyRecord], require_protection: bool = False) -> None:
        self.path = path
        self._active_key_id = active_key_id
        self.records = records
        self.require_protection = require_protection

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    @classmethod
    def load(cls, path: str, legacy_root_path: Optional[str] = None, require_protection: bool = False) -> "KeyRing":
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            records = [
                KeyRecord(
                    key_id=item["key_id"],
                    created_ts=item["created_ts"],
                    key_b64=item["key_b64"],
                    protected=bool(item.get("protected", False)),
                )
                for item in data.get("keys", [])
            ]
            ring = cls(path, data.get("active_key_id", records[0].key_id if records else ""), records, require_protection=require_protection)
            ring._verify_protection()
            return ring

        if legacy_root_path and os.path.exists(legacy_root_path):
            root = load_root_key(legacy_root_path)
            ring = cls._from_key(path, root, key_id="legacy", require_protection=require_protection)
            ring.save()
            return ring

        root = os.urandom(32)
        ring = cls._from_key(path, root, require_protection=require_protection)
        ring.save()
        return ring

    @classmethod
    def _from_key(cls, path: str, key: bytes, key_id: Optional[str] = None, require_protection: bool = False) -> "KeyRing":
        key_id = key_id or _new_id()
        created_ts = datetime.now(timezone.utc).isoformat()
        protected_key, protected = _protect(key)
        if require_protection and os.name == "nt" and not protected:
            raise RuntimeError("DPAPI protection required but unavailable")
        record = KeyRecord(
            key_id=key_id,
            created_ts=created_ts,
            key_b64=base64.b64encode(protected_key).decode("ascii"),
            protected=protected,
        )
        return cls(path, key_id, [record], require_protection=require_protection)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = {
            "schema_version": 1,
            "active_key_id": self._active_key_id,
            "keys": [
                {
                    "key_id": record.key_id,
                    "created_ts": record.created_ts,
                    "key_b64": record.key_b64,
                    "protected": record.protected,
                }
                for record in self.records
            ],
        }
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

    def active_key(self) -> tuple[str, bytes]:
        return self._active_key_id, self.key_for(self._active_key_id)

    def key_for(self, key_id: str) -> bytes:
        for record in self.records:
            if record.key_id == key_id:
                return record.key_bytes()
        raise KeyError(f"Unknown key id: {key_id}")

    def all_keys(self) -> dict[str, bytes]:
        return {record.key_id: record.key_bytes() for record in self.records}

    def rotate(self) -> str:
        key_id = _new_id()
        created_ts = datetime.now(timezone.utc).isoformat()
        key = os.urandom(32)
        protected_key, protected = _protect(key)
        if self.require_protection and os.name == "nt" and not protected:
            raise RuntimeError("DPAPI protection required but unavailable")
        self.records.append(
            KeyRecord(
                key_id=key_id,
                created_ts=created_ts,
                key_b64=base64.b64encode(protected_key).decode("ascii"),
                protected=protected,
            )
        )
        self._active_key_id = key_id
        self.save()
        return key_id

    def _verify_protection(self) -> None:
        if not self.require_protection:
            return
        if os.name != "nt":
            raise RuntimeError("DPAPI protection required on Windows only")
        for record in self.records:
            if not record.protected:
                raise RuntimeError("DPAPI protection required but key is unprotected")
            try:
                _ = record.key_bytes()
            except Exception as exc:
                raise RuntimeError("DPAPI unprotect failed") from exc


@dataclass
class KeyringStatus:
    active_key_id: str
    keyring_path: str


class Keyring(KeyRing):
    """Alias for KeyRing to match spec naming."""

    def status(self) -> KeyringStatus:
        return KeyringStatus(active_key_id=self.active_key_id, keyring_path=self.path)
