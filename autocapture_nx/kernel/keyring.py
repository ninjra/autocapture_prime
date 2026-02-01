"""Keyring management for root keys with rotation."""

from __future__ import annotations

import base64
import json
import os
import uuid
from pathlib import Path
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

BACKEND_AUTO = "auto"
BACKEND_PORTABLE = "portable_file"
BACKEND_CREDMAN = "windows_credential_manager"


def _normalize_backend(backend: str | None) -> str:
    if not backend:
        return BACKEND_PORTABLE
    value = str(backend).strip().lower()
    if value in {BACKEND_AUTO, BACKEND_PORTABLE, BACKEND_CREDMAN}:
        return value
    return BACKEND_PORTABLE


def _resolve_backend(backend: str | None) -> str:
    normalized = _normalize_backend(backend)
    if normalized == BACKEND_AUTO:
        return BACKEND_CREDMAN if os.name == "nt" else BACKEND_PORTABLE
    if normalized == BACKEND_CREDMAN and os.name != "nt":
        return BACKEND_PORTABLE
    return normalized


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


def _credman_read(name: str) -> dict | None:
    if os.name != "nt":
        return None
    try:
        from autocapture_nx.windows.credential_manager import read_credential

        raw = read_credential(name)
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _credman_write(name: str, payload: dict) -> bool:
    if os.name != "nt":
        return False
    try:
        from autocapture_nx.windows.credential_manager import write_credential

        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return bool(write_credential(name, raw))
    except Exception:
        return False


def _load_payload(path: str, backend: str, credential_name: str | None) -> dict | None:
    if backend == BACKEND_CREDMAN:
        if credential_name:
            return _credman_read(credential_name)
        return None
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return None


def _save_payload(path: str, backend: str, credential_name: str | None, payload: dict) -> None:
    if backend == BACKEND_CREDMAN and credential_name:
        if not _credman_write(credential_name, payload):
            raise RuntimeError("Credential Manager write failed")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


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
    def __init__(
        self,
        path: str,
        purposes: dict[str, PurposeKeySet],
        require_protection: bool = False,
        *,
        backend: str = BACKEND_PORTABLE,
        credential_name: str | None = None,
    ) -> None:
        self.path = path
        self._purposes = purposes
        self.require_protection = require_protection
        self.backend = _resolve_backend(backend)
        self.credential_name = credential_name

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

    def key_version_for(self, purpose: str | None, key_id: str) -> int:
        keyset = self._keyset(purpose)
        for idx, record in enumerate(keyset.records, start=1):
            if record.key_id == key_id:
                return idx
        raise KeyError(f"Unknown key id: {key_id}")

    def active_key_version(self, purpose: str | None = None) -> int:
        keyset = self._keyset(purpose)
        return self.key_version_for(keyset.purpose, keyset.active_key_id)

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

    def set_active(self, purpose: str | None, key_id: str) -> None:
        keyset = self._keyset(purpose)
        if key_id not in {record.key_id for record in keyset.records}:
            raise KeyError(f"Unknown key id: {key_id}")
        keyset.active_key_id = key_id
        self.save()

    @classmethod
    def load(
        cls,
        path: str,
        legacy_root_path: Optional[str] = None,
        require_protection: bool = False,
        *,
        backend: str | None = None,
        credential_name: str | None = None,
    ) -> "KeyRing":
        resolved_backend = _resolve_backend(backend)
        credential_name = credential_name or "autocapture.keyring"
        data = _load_payload(path, resolved_backend, credential_name)
        if data is None and resolved_backend == BACKEND_CREDMAN and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            try:
                _save_payload(path, resolved_backend, credential_name, data)
            except Exception:
                pass
        if data is not None:
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
                ring = cls(
                    path,
                    legacy_purposes,
                    require_protection=require_protection,
                    backend=resolved_backend,
                    credential_name=credential_name,
                )
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
            ring = cls(
                path,
                purposes,
                require_protection=require_protection,
                backend=resolved_backend,
                credential_name=credential_name,
            )
            ring._verify_protection()
            if dirty:
                ring.save()
            return ring

        if legacy_root_path and os.path.exists(legacy_root_path):
            root = load_root_key(legacy_root_path)
            ring = cls._from_legacy_root(
                path,
                root,
                require_protection=require_protection,
                backend=resolved_backend,
                credential_name=credential_name,
            )
            ring.save()
            return ring

        purposes = {purpose: cls._new_keyset(purpose, require_protection=require_protection) for purpose in PURPOSES}
        ring = cls(
            path,
            purposes,
            require_protection=require_protection,
            backend=resolved_backend,
            credential_name=credential_name,
        )
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
        *,
        backend: str = BACKEND_PORTABLE,
        credential_name: str | None = None,
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
        return cls(
            path,
            purposes,
            require_protection=require_protection,
            backend=backend,
            credential_name=credential_name,
        )

    def _keyset(self, purpose: str | None) -> PurposeKeySet:
        normalized = _normalize_purpose(purpose)
        if normalized not in self._purposes:
            self._purposes[normalized] = self._new_keyset(normalized, require_protection=self.require_protection)
            self.save()
        return self._purposes[normalized]

    def save(self) -> None:
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
        _save_payload(self.path, self.backend, self.credential_name, payload)
        if self.backend != BACKEND_CREDMAN:
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
    backend: str
    credential_name: str | None = None


class Keyring(KeyRing):
    """Alias for KeyRing to match spec naming."""

    def status(self) -> KeyringStatus:
        active = {purpose: keyset.active_key_id for purpose, keyset in self._purposes.items()}
        return KeyringStatus(
            active_key_ids=active,
            keyring_path=self.path,
            backend=self.backend,
            credential_name=self.credential_name,
        )


def _serialize_keyring(keyring: KeyRing, *, unprotect: bool) -> dict:
    purposes: dict[str, dict] = {}
    for purpose in keyring.purposes():
        records = []
        for record in keyring.records_for(purpose):
            if unprotect:
                raw = record.key_bytes()
                key_b64 = base64.b64encode(raw).decode("ascii")
                protected = False
            else:
                key_b64 = record.key_b64
                protected = bool(record.protected)
            records.append(
                {
                    "key_id": record.key_id,
                    "created_ts": record.created_ts,
                    "key_b64": key_b64,
                    "protected": protected,
                }
            )
        purposes[purpose] = {
            "active_key_id": keyring.active_key_id_for(purpose),
            "keys": records,
        }
    return {"schema_version": 2, "purposes": purposes}


def _deserialize_keyring(
    payload: dict,
    *,
    path: str,
    require_protection: bool,
    backend: str,
    credential_name: str | None,
) -> KeyRing:
    schema_version = int(payload.get("schema_version", 1) or 1)
    if schema_version == 1:
        purposes_payload = {purpose: payload for purpose in PURPOSES}
    else:
        purposes_payload = payload.get("purposes", {})
    purposes: dict[str, PurposeKeySet] = {}
    for purpose, data in purposes_payload.items():
        records = []
        for item in data.get("keys", []):
            key_bytes = base64.b64decode(item["key_b64"])
            protected_key, protected = _protect(key_bytes)
            if require_protection and os.name == "nt" and not protected:
                raise RuntimeError("DPAPI protection required but unavailable")
            records.append(
                KeyRecord(
                    key_id=item["key_id"],
                    created_ts=item["created_ts"],
                    key_b64=base64.b64encode(protected_key).decode("ascii"),
                    protected=protected,
                )
            )
        active_key_id = data.get("active_key_id", records[0].key_id if records else "")
        purposes[str(purpose)] = PurposeKeySet(str(purpose), active_key_id, records)
    return KeyRing(
        path,
        purposes,
        require_protection=require_protection,
        backend=backend,
        credential_name=credential_name,
    )


def export_keyring_bundle(
    keyring: KeyRing,
    *,
    path: str,
    passphrase: str,
    kdf_salt: bytes | None = None,
) -> dict:
    """Export keyring as encrypted bundle (portable across machines)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    payload = _serialize_keyring(keyring, unprotect=True)
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    salt = kdf_salt or os.urandom(16)
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    key = kdf.derive(passphrase.encode("utf-8"))
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aes.encrypt(nonce, encoded, b"autocapture.keyring.bundle.v1")
    bundle = {
        "schema_version": 1,
        "kdf": {"type": "scrypt", "n": 2**14, "r": 8, "p": 1, "salt_b64": base64.b64encode(salt).decode("ascii")},
        "cipher": {
            "nonce_b64": base64.b64encode(nonce).decode("ascii"),
            "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
        },
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(bundle, handle, sort_keys=True, indent=2)
    return bundle


def import_keyring_bundle(
    *,
    path: str,
    passphrase: str,
    keyring_path: str,
    require_protection: bool,
    backend: str,
    credential_name: str | None,
) -> KeyRing:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    kdf_cfg = bundle.get("kdf", {})
    if kdf_cfg.get("type") != "scrypt":
        raise RuntimeError("Unsupported KDF for keyring bundle")
    salt = base64.b64decode(kdf_cfg.get("salt_b64", ""))
    kdf = Scrypt(salt=salt, length=32, n=int(kdf_cfg.get("n", 2**14)), r=int(kdf_cfg.get("r", 8)), p=int(kdf_cfg.get("p", 1)))
    key = kdf.derive(passphrase.encode("utf-8"))
    cipher_cfg = bundle.get("cipher", {})
    nonce = base64.b64decode(cipher_cfg.get("nonce_b64", ""))
    ciphertext = base64.b64decode(cipher_cfg.get("ciphertext_b64", ""))
    aes = AESGCM(key)
    plaintext = aes.decrypt(nonce, ciphertext, b"autocapture.keyring.bundle.v1")
    payload = json.loads(plaintext.decode("utf-8"))
    ring = _deserialize_keyring(
        payload,
        path=keyring_path,
        require_protection=require_protection,
        backend=backend,
        credential_name=credential_name,
    )
    ring.save()
    return ring
