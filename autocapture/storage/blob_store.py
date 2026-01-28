"""Encrypted blob store with binary payloads."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from autocapture_nx.kernel.crypto import (
    EncryptedBlob,
    EncryptedBlobRaw,
    decrypt_bytes,
    decrypt_bytes_raw,
    derive_key,
    encrypt_bytes_raw,
)
from autocapture_nx.kernel.keyring import KeyRing


class BlobStore:
    def __init__(self, root: str | Path, keyring: KeyRing) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.keyring = keyring
        self._purpose = "media"
        self._count_cache: int | None = None

    def _derive(self, key_id: str) -> bytes:
        root = self.keyring.key_for(self._purpose, key_id)
        return derive_key(root, "blob_store")

    def _candidate_keys(self, key_id: str | None) -> list[bytes]:
        keys: list[bytes] = []
        seen: set[str] = set()
        if key_id:
            try:
                keys.append(self._derive(key_id))
                seen.add(key_id)
            except KeyError:
                pass
        active_id, active_root = self.keyring.active_key(self._purpose)
        if active_id not in seen:
            keys.append(derive_key(active_root, "blob_store"))
            seen.add(active_id)
        for key_id, root in self.keyring.all_keys(self._purpose).items():
            if key_id in seen:
                continue
            keys.append(derive_key(root, "blob_store"))
            seen.add(key_id)
        return keys

    def _pack_blob(self, blob: EncryptedBlobRaw) -> bytes:
        key_id_bytes = blob.key_id.encode("utf-8") if blob.key_id else b""
        return b"".join(
            [
                BLOB_MAGIC,
                struct.pack(">H", len(key_id_bytes)),
                key_id_bytes,
                struct.pack(">H", len(blob.nonce)),
                blob.nonce,
                struct.pack(">Q", len(blob.ciphertext)),
                blob.ciphertext,
            ]
        )

    def _unpack_blob(self, data: bytes) -> EncryptedBlobRaw:
        offset = 0
        if data[: len(BLOB_MAGIC)] != BLOB_MAGIC:
            raise ValueError("Unknown blob format")
        offset += len(BLOB_MAGIC)
        key_len = struct.unpack(">H", data[offset : offset + 2])[0]
        offset += 2
        key_id = data[offset : offset + key_len].decode("utf-8") if key_len else None
        offset += key_len
        nonce_len = struct.unpack(">H", data[offset : offset + 2])[0]
        offset += 2
        nonce = data[offset : offset + nonce_len]
        offset += nonce_len
        cipher_len = struct.unpack(">Q", data[offset : offset + 8])[0]
        offset += 8
        ciphertext = data[offset : offset + cipher_len]
        return EncryptedBlobRaw(nonce=nonce, ciphertext=ciphertext, key_id=key_id)

    def put(self, data: bytes) -> str:
        blob_id = hashlib.sha256(data).hexdigest()
        path = self.root / f"{blob_id}.blob"
        if path.exists():
            return blob_id
        key_id, root = self.keyring.active_key(self._purpose)
        key = derive_key(root, "blob_store")
        blob = encrypt_bytes_raw(key, data, key_id=key_id)
        payload = self._pack_blob(blob)
        try:
            with path.open("xb") as handle:
                handle.write(payload)
        except FileExistsError:
            return blob_id
        if self._count_cache is not None:
            self._count_cache += 1
        return blob_id

    def get(self, blob_id: str) -> bytes:
        path = self.root / f"{blob_id}.blob"
        data = path.read_bytes()
        if data.startswith(BLOB_MAGIC):
            blob = self._unpack_blob(data)
            for key in self._candidate_keys(blob.key_id):
                try:
                    return decrypt_bytes_raw(key, blob)
                except Exception:
                    continue
            raise RuntimeError(f"Decrypt failed for blob {blob_id}")
        payload = json.loads(data.decode("utf-8"))
        blob = EncryptedBlob(
            nonce_b64=payload["nonce_b64"],
            ciphertext_b64=payload["ciphertext_b64"],
            key_id=payload.get("key_id"),
        )
        for key in self._candidate_keys(blob.key_id):
            try:
                return decrypt_bytes(key, blob)
            except Exception:
                continue
        raise RuntimeError(f"Decrypt failed for blob {blob_id}")

    def exists(self, blob_id: str) -> bool:
        return (self.root / f"{blob_id}.blob").exists()

    def count(self) -> int:
        if self._count_cache is None:
            self._count_cache = len(list(self.root.glob("*.blob")))
        return self._count_cache


BLOB_MAGIC = b"ACNXBLOB1"


def create_blob_store(plugin_id: str):
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config
    from autocapture.storage.keys import load_keyring

    config = load_config(default_config_paths(), safe_mode=False)
    root = Path(config.get("storage", {}).get("blob_dir", "data/blobs"))
    return BlobStore(root, load_keyring(config))
