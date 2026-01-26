"""Encrypted metadata store built on SQLite."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.crypto import EncryptedBlob, decrypt_bytes, derive_key, encrypt_bytes
from autocapture_nx.kernel.keyring import KeyRing


@dataclass
class EncryptedRecord:
    record_id: str
    nonce_b64: str
    ciphertext_b64: str
    key_id: str


class EncryptedMetadataStore:
    def __init__(self, path: str | Path, keyring: KeyRing) -> None:
        self.path = Path(path)
        self.keyring = keyring
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS records (record_id TEXT PRIMARY KEY, nonce_b64 TEXT, ciphertext_b64 TEXT, key_id TEXT)"
        )
        self._conn.commit()

    def _derive(self, key_id: str) -> bytes:
        root = self.keyring.key_for(key_id)
        return derive_key(root, "metadata_store")

    def put(self, record_id: str, payload: dict[str, Any]) -> None:
        existing = self.get(record_id, default=None)
        if existing is not None:
            if existing == payload:
                return
            raise ValueError(f"record already exists: {record_id}")

        key_id, root = self.keyring.active_key()
        key = derive_key(root, "metadata_store")
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        blob = encrypt_bytes(key, data, key_id=key_id)
        try:
            self._conn.execute(
                "INSERT INTO records (record_id, nonce_b64, ciphertext_b64, key_id) VALUES (?, ?, ?, ?)",
                (record_id, blob.nonce_b64, blob.ciphertext_b64, key_id),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            existing = self.get(record_id, default=None)
            if existing == payload:
                return
            raise

    def get(self, record_id: str, default: Any | None = None) -> Any:
        cur = self._conn.execute(
            "SELECT nonce_b64, ciphertext_b64, key_id FROM records WHERE record_id = ?",
            (record_id,),
        )
        row = cur.fetchone()
        if not row:
            return default
        blob = EncryptedBlob(nonce_b64=row[0], ciphertext_b64=row[1], key_id=row[2])
        key = self._derive(row[2])
        data = decrypt_bytes(key, blob)
        return json.loads(data.decode("utf-8"))

    def keys(self) -> list[str]:
        cur = self._conn.execute("SELECT record_id FROM records")
        return [row[0] for row in cur.fetchall()]
