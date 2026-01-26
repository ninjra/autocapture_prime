"""Encrypted blob store."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from autocapture_nx.kernel.crypto import EncryptedBlob, decrypt_bytes, derive_key, encrypt_bytes
from autocapture_nx.kernel.keyring import KeyRing


class BlobStore:
    def __init__(self, root: str | Path, keyring: KeyRing) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.keyring = keyring

    def _derive(self, key_id: str) -> bytes:
        root = self.keyring.key_for(key_id)
        return derive_key(root, "blob_store")

    def put(self, data: bytes) -> str:
        blob_id = hashlib.sha256(data).hexdigest()
        path = self.root / f"{blob_id}.blob"
        if path.exists():
            return blob_id
        key_id, root = self.keyring.active_key()
        key = derive_key(root, "blob_store")
        blob = encrypt_bytes(key, data, key_id=key_id)
        payload = {
            "nonce_b64": blob.nonce_b64,
            "ciphertext_b64": blob.ciphertext_b64,
            "key_id": key_id,
        }
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True))
        except FileExistsError:
            return blob_id
        return blob_id

    def get(self, blob_id: str) -> bytes:
        path = self.root / f"{blob_id}.blob"
        payload = json.loads(path.read_text(encoding="utf-8"))
        blob = EncryptedBlob(
            nonce_b64=payload["nonce_b64"],
            ciphertext_b64=payload["ciphertext_b64"],
            key_id=payload.get("key_id"),
        )
        key = self._derive(payload["key_id"])
        return decrypt_bytes(key, blob)

    def exists(self, blob_id: str) -> bool:
        return (self.root / f"{blob_id}.blob").exists()


def create_blob_store(plugin_id: str):
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config
    from autocapture.storage.keys import load_keyring

    config = load_config(default_config_paths(), safe_mode=False)
    root = Path(config.get("storage", {}).get("blob_dir", "data/blobs"))
    return BlobStore(root, load_keyring(config))
