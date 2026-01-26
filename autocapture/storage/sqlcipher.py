"""SQLCipher-compatible metadata store."""

from __future__ import annotations

from typing import Any

from autocapture.storage.database import EncryptedMetadataStore
from autocapture.storage.keys import load_keyring


class SqlCipherMetadataStore(EncryptedMetadataStore):
    """Fallback store using app-layer encryption when SQLCipher isn't available."""


def open_metadata_store(config: dict[str, Any]) -> EncryptedMetadataStore:
    storage_cfg = config.get("storage", {})
    path = storage_cfg.get("metadata_path", "data/metadata.db")
    keyring = load_keyring(config)
    try:
        pass  # type: ignore
        # SQLCipher integration can be added when library is available.
        # For now, use encrypted store with derived keys.
    except Exception:
        return SqlCipherMetadataStore(path, keyring)
    return SqlCipherMetadataStore(path, keyring)
