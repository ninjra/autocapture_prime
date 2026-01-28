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


DEFAULT_PURPOSE = "metadata"
PURPOSE_ALIASES = {
    "tokenization": "entity_tokens",
    "tokens": "entity_tokens",
}
PURPOSES = ("metadata", "media", "entity_tokens", "anchor")


def _new_id() -> str:
    if hasattr(uuid, "uuid7"):
        return str(uuid.uuid7())  # type: ignore[attr-defined]
    return str(uuid.uuid4())


def _normalize_purpose(purpose: str | None) -> str:
    if not purpose:
        return DEFAULT_PURPOSE
    key = str(purpose).strip().lower()
    return PURPOSE_ALIASES.get(key, key)


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


@dataclass
class PurposeKeySet:
    purpose: str
    active_key_id: str
    records: list[KeyRecord]


class KeyRing:
    def __init__(self, path: str, purposes: dict[str, PurposeKeySet], require_protection: bool = False) -> None:
        self.path = path
        self._purposes = purposes
        self.require_protection = require_protection

    @property
    def active_key_id(self) -> str:
        return self.active_key_id_for(DEFAULT_PURPOSE)

    @property
    def records(self) -> list[KeyRecord]:
        return list(self._purposes[_normalize_purpose(DEFAULT_PURPOSE)].records)

    def purposes(self) -> list[str]:
        return sorted(self._purposes.keys())

    def active_key_id_for(self, purpose: str | None = None) -> str:
        keyset = self._keyset(purpose)
        return keyset.active_key_id

    def active_key(self, purpose: str | None = None) -> tuple[str, bytes]:
        keyset = self._keyset(purpose)
        return keyset.active_key_id, self.key_for(keyset.purpose, keyset.active_key_id)

    def key_for(self, purpose: str | None, key_id: str) -> bytes:
        keyset = self._keyset(purpose)
        for record in keyset.records:
            if record.key_id == key_id:
                return record.key_bytes()
        raise KeyError(f"Unknown key id: {key_id}")

    def all_keys(self, purpose: str | None = None) -> dict[str, bytes]:
        keyset = self._keyset(purpose)
        return {record.key_id: record.key_bytes() for record in keyset.records}

    def records_for(self, purpose: str | None = None) -> list[KeyRecord]:
        return self._keyset(purpose).records

    def rotate(self, purpose: str | None = None) -> str:
        keyset = self._keyset(purpose)
        key_id = _new_id()
        created_ts = datetime.now(timezone.utc).isoformat()
        key = os.urandom(32)
        protected_key, protected = _protect(key)
        if self.require_protection and os.name == "nt" and not protected:
            raise RuntimeError("DPAPI protection required but unavailable")
        keyset.records.append(
            KeyRecord(
                key_id=key_id,
                created_ts=created_ts,
                key_b64=base64.b64encode(protected_key).decode("ascii"),
                protected=protected,
            )
        )
        keyset.active_key_id = key_id
        self.save()
        return key_id

    @classmethod
    def load(cls, path: str, legacy_root_path: Optional[str] = None, require_protection: bool = False) -> "KeyRing":
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            schema_version = int(data.get("schema_version", 1) or 1)
            if schema_version == 1:
                records = [
                    KeyRecord(
                        key_id=item["key_id"],
                        created_ts=item["created_ts"],
                        key_b64=item["key_b64"],
                        protected=bool(item.get("protected", False)),
                    )
                    for item in data.get("keys", [])
                ]
                active_key_id = data.get("active_key_id", records[0].key_id if records else "")
                legacy_purposes = {
                    purpose: PurposeKeySet(purpose, active_key_id, list(records))
                    for purpose in PURPOSES
                }
                ring = cls(path, legacy_purposes, require_protection=require_protection)
                ring._verify_protection()
                ring.save()
                return ring
            if schema_version != 2:
                raise RuntimeError(f"Unsupported keyring schema_version: {schema_version}")
            purposes: dict[str, PurposeKeySet] = {}
            dirty = False
            raw_purposes = data.get("purposes", {})
            if not isinstance(raw_purposes, dict):
                raise RuntimeError("Invalid keyring purposes payload")
            for purpose, payload in raw_purposes.items():
                if not isinstance(payload, dict):
                    continue
                records = [
                    KeyRecord(
                        key_id=item["key_id"],
                        created_ts=item["created_ts"],
                        key_b64=item["key_b64"],
                        protected=bool(item.get("protected", False)),
                    )
                    for item in payload.get("keys", [])
                ]
                active_key_id = payload.get("active_key_id", records[0].key_id if records else "")
                purposes[str(purpose)] = PurposeKeySet(str(purpose), active_key_id, records)
            for purpose in PURPOSES:
                if purpose not in purposes:
                    purposes[purpose] = cls._new_keyset(purpose, require_protection=require_protection)
                    dirty = True
            ring = cls(path, purposes, require_protection=require_protection)
            ring._verify_protection()
            if dirty:
                ring.save()
            return ring

        if legacy_root_path and os.path.exists(legacy_root_path):
            root = load_root_key(legacy_root_path)
            ring = cls._from_legacy_root(path, root, require_protection=require_protection)
            ring.save()
            return ring

        purposes = {purpose: cls._new_keyset(purpose, require_protection=require_protection) for purpose in PURPOSES}
        ring = cls(path, purposes, require_protection=require_protection)
        ring.save()
        return ring

    @classmethod
    def _new_keyset(cls, purpose: str, require_protection: bool = False) -> PurposeKeySet:
        key_id = _new_id()
        created_ts = datetime.now(timezone.utc).isoformat()
        key = os.urandom(32)
        protected_key, protected = _protect(key)
        if require_protection and os.name == "nt" and not protected:
            raise RuntimeError("DPAPI protection required but unavailable")
        record = KeyRecord(
            key_id=key_id,
            created_ts=created_ts,
            key_b64=base64.b64encode(protected_key).decode("ascii"),
            protected=protected,
        )
        return PurposeKeySet(purpose, key_id, [record])

    @classmethod
    def _from_legacy_root(
        cls,
        path: str,
        key: bytes,
        key_id: Optional[str] = None,
        require_protection: bool = False,
    ) -> "KeyRing":
        key_id = key_id or "legacy"
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
        purposes = {purpose: PurposeKeySet(purpose, key_id, [record]) for purpose in PURPOSES}
        return cls(path, purposes, require_protection=require_protection)

    def _keyset(self, purpose: str | None) -> PurposeKeySet:
        normalized = _normalize_purpose(purpose)
        if normalized not in self._purposes:
            self._purposes[normalized] = self._new_keyset(normalized, require_protection=self.require_protection)
            self.save()
        return self._purposes[normalized]

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = {
            "schema_version": 2,
            "purposes": {
                purpose: {
                    "active_key_id": keyset.active_key_id,
                    "keys": [
                        {
                            "key_id": record.key_id,
                            "created_ts": record.created_ts,
                            "key_b64": record.key_b64,
                            "protected": record.protected,
                        }
                        for record in keyset.records
                    ],
                }
                for purpose, keyset in sorted(self._purposes.items())
            },
        }
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        try:
            from autocapture_nx.windows.acl import harden_path_permissions

            harden_path_permissions(self.path, is_dir=False)
            harden_path_permissions(os.path.dirname(self.path), is_dir=True)
        except Exception:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def _verify_protection(self) -> None:
        if not self.require_protection:
            return
        if os.name != "nt":
            raise RuntimeError("DPAPI protection required on Windows only")
        for keyset in self._purposes.values():
            for record in keyset.records:
                if not record.protected:
                    raise RuntimeError("DPAPI protection required but key is unprotected")
                try:
                    _ = record.key_bytes()
                except Exception as exc:
                    raise RuntimeError("DPAPI unprotect failed") from exc


@dataclass
class KeyringStatus:
    active_key_ids: dict[str, str]
    keyring_path: str


class Keyring(KeyRing):
    """Alias for KeyRing to match spec naming."""

    def status(self) -> KeyringStatus:
        active = {purpose: keyset.active_key_id for purpose, keyset in self._purposes.items()}
        return KeyringStatus(active_key_ids=active, keyring_path=self.path)
