"""Encrypted storage plugin using AES-GCM."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from autocapture_nx.kernel.crypto import EncryptedBlob, decrypt_bytes, derive_key, encrypt_bytes
from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class DerivedKeyProvider:
    def __init__(self, keyring: KeyRing, purpose: str) -> None:
        self._keyring = keyring
        self._purpose = purpose

    def active(self) -> tuple[str, bytes]:
        key_id, root = self._keyring.active_key()
        return key_id, derive_key(root, self._purpose)

    def for_id(self, key_id: str) -> bytes:
        root = self._keyring.key_for(key_id)
        return derive_key(root, self._purpose)

    def candidates(self, key_id: str | None) -> list[bytes]:
        keys: list[bytes] = []
        if key_id:
            try:
                keys.append(self.for_id(key_id))
                return keys
            except KeyError:
                pass
        active_id, active_root = self._keyring.active_key()
        keys.append(derive_key(active_root, self._purpose))
        for record in self._keyring.records:
            if record.key_id == active_id:
                continue
            keys.append(derive_key(record.key_bytes(), self._purpose))
        return keys


class EncryptedJSONStore:
    def __init__(self, root_dir: str, key_provider: DerivedKeyProvider, require_decrypt: bool = False) -> None:
        self._root = root_dir
        self._key_provider = key_provider
        self._require_decrypt = require_decrypt
        os.makedirs(self._root, exist_ok=True)

    def _path(self, record_id: str) -> str:
        safe = record_id.replace("/", "_")
        return os.path.join(self._root, f"{safe}.json")

    def put(self, record_id: str, value: Any) -> None:
        payload = json.dumps(value, sort_keys=True).encode("utf-8")
        key_id, key = self._key_provider.active()
        blob = encrypt_bytes(key, payload, key_id=key_id)
        with open(self._path(record_id), "w", encoding="utf-8") as handle:
            json.dump(blob.__dict__, handle, sort_keys=True)

    def get(self, record_id: str, default: Any = None) -> Any:
        path = self._path(record_id)
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        blob = EncryptedBlob(**data)
        payload = None
        for key in self._key_provider.candidates(blob.key_id):
            try:
                payload = decrypt_bytes(key, blob)
                break
            except Exception:
                continue
        if payload is None:
            if self._require_decrypt:
                raise RuntimeError(f"Decrypt failed for metadata record {record_id}")
            return default
        return json.loads(payload.decode("utf-8"))

    def keys(self) -> list[str]:
        ids = []
        for filename in os.listdir(self._root):
            if not filename.endswith(".json"):
                continue
            ids.append(filename[:-5])
        return sorted(ids)

    def rotate(self, _new_key: bytes | None = None) -> int:
        count = 0
        for record_id in self.keys():
            value = self.get(record_id)
            self.put(record_id, value)
            count += 1
        return count


class EncryptedBlobStore:
    def __init__(self, root_dir: str, key_provider: DerivedKeyProvider, require_decrypt: bool = False) -> None:
        self._root = root_dir
        self._key_provider = key_provider
        self._require_decrypt = require_decrypt
        os.makedirs(self._root, exist_ok=True)

    def _path(self, record_id: str) -> str:
        safe = record_id.replace("/", "_")
        return os.path.join(self._root, f"{safe}.json")

    def _path_stream(self, record_id: str) -> str:
        safe = record_id.replace("/", "_")
        return os.path.join(self._root, f"{safe}.jsonl")

    def put(self, record_id: str, data: bytes) -> None:
        key_id, key = self._key_provider.active()
        blob = encrypt_bytes(key, data, key_id=key_id)
        stream_path = self._path_stream(record_id)
        if os.path.exists(stream_path):
            os.remove(stream_path)
        with open(self._path(record_id), "w", encoding="utf-8") as handle:
            json.dump(blob.__dict__, handle, sort_keys=True)

    def put_stream(self, record_id: str, stream, chunk_size: int = 1024 * 1024) -> None:
        key_id, key = self._key_provider.active()
        path = self._path_stream(record_id)
        blob_path = self._path(record_id)
        if os.path.exists(blob_path):
            os.remove(blob_path)
        with open(path, "w", encoding="utf-8") as handle:
            header = {"format": "chunked", "schema_version": 1, "key_id": key_id}
            handle.write(json.dumps(header, sort_keys=True))
            handle.write("\n")
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                blob = encrypt_bytes(key, chunk, key_id=key_id)
                handle.write(json.dumps({"nonce_b64": blob.nonce_b64, "ciphertext_b64": blob.ciphertext_b64}, sort_keys=True))
                handle.write("\n")

    def get(self, record_id: str, default: bytes | None = None) -> bytes | None:
        path = self._path(record_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            blob = EncryptedBlob(**data)
            for key in self._key_provider.candidates(blob.key_id):
                try:
                    return decrypt_bytes(key, blob)
                except Exception:
                    continue
            if self._require_decrypt:
                raise RuntimeError(f"Decrypt failed for blob record {record_id}")
            return default
        stream_path = self._path_stream(record_id)
        if not os.path.exists(stream_path):
            return default
        with open(stream_path, "r", encoding="utf-8") as handle:
            header_line = handle.readline()
            if not header_line:
                if self._require_decrypt:
                    raise RuntimeError(f"Decrypt failed for blob record {record_id}")
                return default
            header = json.loads(header_line)
            key_id = header.get("key_id")
            key_candidates = self._key_provider.candidates(key_id)
            for key in key_candidates:
                try:
                    handle.seek(0)
                    handle.readline()
                    payload = bytearray()
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        chunk_data = json.loads(line)
                        blob = EncryptedBlob(**chunk_data)
                        payload.extend(decrypt_bytes(key, blob))
                    return bytes(payload)
                except Exception:
                    continue
        if self._require_decrypt:
            raise RuntimeError(f"Decrypt failed for blob record {record_id}")
        return default

    def keys(self) -> list[str]:
        ids: set[str] = set()
        for filename in os.listdir(self._root):
            if filename.endswith(".json"):
                ids.add(filename[:-5])
            elif filename.endswith(".jsonl"):
                ids.add(filename[:-6])
        return sorted(ids)

    def rotate(self, _new_key: bytes | None = None) -> int:
        count = 0
        for record_id in self.keys():
            value = self.get(record_id)
            if value is None:
                continue
            self.put(record_id, value)
            count += 1
        return count


class EntityMapStore:
    def __init__(self, root_dir: str, key_provider: DerivedKeyProvider, persist: bool, require_decrypt: bool = False) -> None:
        self._root = root_dir
        self._key_provider = key_provider
        self._persist = persist
        self._require_decrypt = require_decrypt
        os.makedirs(self._root, exist_ok=True)
        self._path = os.path.join(self._root, "entity_map.json")
        self._data: dict[str, dict[str, str]] = {}
        if self._persist and os.path.exists(self._path):
            self._data = self._load()

    def _load(self) -> dict[str, dict[str, str]]:
        with open(self._path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        blob = EncryptedBlob(**payload)
        decrypted = None
        for key in self._key_provider.candidates(blob.key_id):
            try:
                decrypted = decrypt_bytes(key, blob)
                break
            except Exception:
                continue
        if decrypted is None:
            if self._require_decrypt:
                raise RuntimeError("Decrypt failed for entity map")
            return {}
        return json.loads(decrypted.decode("utf-8"))

    def _save(self) -> None:
        payload = json.dumps(self._data, sort_keys=True).encode("utf-8")
        key_id, key = self._key_provider.active()
        blob = encrypt_bytes(key, payload, key_id=key_id)
        with open(self._path, "w", encoding="utf-8") as handle:
            json.dump(blob.__dict__, handle, sort_keys=True)

    def put(self, token: str, value: str, kind: str) -> None:
        self._data[token] = {"value": value, "kind": kind}
        if self._persist:
            self._save()

    def get(self, token: str) -> dict[str, str] | None:
        return self._data.get(token)

    def items(self) -> dict[str, dict[str, str]]:
        return dict(self._data)

    def rotate(self, _new_key: bytes | None = None) -> int:
        if self._persist:
            self._save()
            return 1
        return 0


class EncryptedStoragePlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        storage_cfg = context.config.get("storage", {})
        crypto_cfg = storage_cfg.get("crypto", {})
        keyring_path = crypto_cfg.get("keyring_path", "data/vault/keyring.json")
        root_key_path = crypto_cfg.get("root_key_path", "data/vault/root.key")
        encryption_required = storage_cfg.get("encryption_required", False)
        require_protection = bool(encryption_required and os.name == "nt")
        keyring = KeyRing.load(keyring_path, legacy_root_path=root_key_path, require_protection=require_protection)
        self._keyring = keyring
        meta_provider = DerivedKeyProvider(keyring, "metadata")
        media_provider = DerivedKeyProvider(keyring, "media")
        entity_provider = DerivedKeyProvider(keyring, "entity_tokens")
        data_dir = storage_cfg.get("data_dir", "data")
        require_decrypt = bool(encryption_required)
        self._metadata = ImmutableMetadataStore(
            EncryptedJSONStore(os.path.join(data_dir, "metadata"), meta_provider, require_decrypt=require_decrypt)
        )
        self._media = EncryptedBlobStore(os.path.join(data_dir, "media"), media_provider, require_decrypt=require_decrypt)
        persist = storage_cfg.get("entity_map", {}).get("persist", True)
        self._entity_map = EntityMapStore(os.path.join(data_dir, "entity_map"), entity_provider, persist, require_decrypt=require_decrypt)

    def capabilities(self) -> dict[str, Any]:
        return {
            "storage.metadata": self._metadata,
            "storage.media": self._media,
            "storage.entity_map": self._entity_map,
            "storage.keyring": self._keyring,
        }


def create_plugin(plugin_id: str, context: PluginContext) -> EncryptedStoragePlugin:
    return EncryptedStoragePlugin(plugin_id, context)
