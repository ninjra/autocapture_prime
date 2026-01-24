"""Key rotation orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.crypto import derive_key
from autocapture_nx.kernel.hashing import sha256_text


def rotate_keys(system) -> dict[str, Any]:
    keyring = system.get("storage.keyring")
    old_id = keyring.active_key_id
    new_id = keyring.rotate()
    _active_id, new_root = keyring.active_key()
    meta_key = derive_key(new_root, "metadata")
    media_key = derive_key(new_root, "media")
    entity_key = derive_key(new_root, "entity_tokens")

    rotated: dict[str, Any] = {}
    metadata = system.get("storage.metadata")
    if hasattr(metadata, "rotate"):
        rotated["metadata"] = metadata.rotate(meta_key)
    media = system.get("storage.media")
    if hasattr(media, "rotate"):
        rotated["media"] = media.rotate(media_key)
    entity = system.get("storage.entity_map")
    if hasattr(entity, "rotate"):
        rotated["entity_map"] = entity.rotate(entity_key)

    policy_snapshot_hash = sha256_text(dumps(system.config))
    ts = datetime.now(timezone.utc).isoformat()
    ledger = system.get("ledger.writer")
    entry = {
        "schema_version": 1,
        "entry_id": f"key_rotation_{new_id}",
        "ts_utc": ts,
        "stage": "security",
        "inputs": [old_id],
        "outputs": [new_id],
        "policy_snapshot_hash": policy_snapshot_hash,
    }
    ledger_hash = ledger.append(entry)
    anchor = system.get("anchor.writer")
    anchor.anchor(ledger_hash)

    return {
        "old_key_id": old_id,
        "new_key_id": new_id,
        "rotated": rotated,
        "ledger_hash": ledger_hash,
    }
