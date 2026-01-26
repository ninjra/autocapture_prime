"""Cryptographic utilities for encryption at rest and tokenization."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


HKDF_SALT = b"autocapture_nx"


@dataclass
class EncryptedBlob:
    nonce_b64: str
    ciphertext_b64: str
    key_id: str | None = None


@dataclass
class EncryptedBlobRaw:
    nonce: bytes
    ciphertext: bytes
    key_id: str | None = None


def load_root_key(path: str) -> bytes:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "rb") as handle:
            data = handle.read()
        if os.name == "nt":
            try:
                from autocapture_nx.windows.dpapi import unprotect

                return unprotect(data)
            except Exception:
                # Fallback to raw key if DPAPI is unavailable
                return data
        return data
    key = os.urandom(32)
    if os.name == "nt":
        try:
            from autocapture_nx.windows.dpapi import protect

            data = protect(key)
        except Exception:
            data = key
    else:
        data = key
    with open(path, "wb") as handle:
        handle.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def derive_key(root_key: bytes, info: str, length: int = 32) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=HKDF_SALT,
        info=info.encode("utf-8"),
    )
    return hkdf.derive(root_key)


def encrypt_bytes(
    key: bytes,
    plaintext: bytes,
    aad: Optional[bytes] = None,
    key_id: Optional[str] = None,
) -> EncryptedBlob:
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aes.encrypt(nonce, plaintext, aad)
    return EncryptedBlob(
        nonce_b64=base64.b64encode(nonce).decode("ascii"),
        ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
        key_id=key_id,
    )


def encrypt_bytes_raw(
    key: bytes,
    plaintext: bytes,
    aad: Optional[bytes] = None,
    key_id: Optional[str] = None,
) -> EncryptedBlobRaw:
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aes.encrypt(nonce, plaintext, aad)
    return EncryptedBlobRaw(nonce=nonce, ciphertext=ciphertext, key_id=key_id)


def decrypt_bytes(key: bytes, blob: EncryptedBlob, aad: Optional[bytes] = None) -> bytes:
    aes = AESGCM(key)
    nonce = base64.b64decode(blob.nonce_b64)
    ciphertext = base64.b64decode(blob.ciphertext_b64)
    return aes.decrypt(nonce, ciphertext, aad)


def decrypt_bytes_raw(key: bytes, blob: EncryptedBlobRaw, aad: Optional[bytes] = None) -> bytes:
    aes = AESGCM(key)
    return aes.decrypt(blob.nonce, blob.ciphertext, aad)
