"""Key rotation orchestration."""

from __future__ import annotations

from typing import Any

from autocapture_nx.kernel.crypto import derive_key


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

    event_builder = system.get("event.builder")
    ledger_hash = event_builder.ledger_entry(
        "security",
        inputs=[old_id],
        outputs=[new_id],
        payload={"event": "key_rotation"},
    )

    return {
        "old_key_id": old_id,
        "new_key_id": new_id,
        "rotated": rotated,
        "ledger_hash": ledger_hash,
    }
