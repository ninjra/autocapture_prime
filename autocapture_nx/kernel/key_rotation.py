"""Key rotation orchestration."""

from __future__ import annotations

from typing import Any
import getpass

from autocapture_nx.kernel.crypto import derive_key


def rotate_keys(system) -> dict[str, Any]:
    keyring = system.get("storage.keyring")
    purposes = ["metadata", "media", "entity_tokens", "anchor"]
    old_ids = {purpose: keyring.active_key_id_for(purpose) for purpose in purposes}

    rotated: dict[str, Any] = {}
    new_ids: dict[str, str] = {}
    for purpose in purposes:
        new_ids[purpose] = keyring.rotate(purpose)

    meta_root = keyring.key_for("metadata", new_ids["metadata"])
    media_root = keyring.key_for("media", new_ids["media"])
    entity_root = keyring.key_for("entity_tokens", new_ids["entity_tokens"])

    metadata = system.get("storage.metadata")
    if hasattr(metadata, "rotate"):
        rotated["metadata"] = metadata.rotate(derive_key(meta_root, "metadata"))
    media = system.get("storage.media")
    if hasattr(media, "rotate"):
        rotated["media"] = media.rotate(derive_key(media_root, "media"))
    entity = system.get("storage.entity_map")
    if hasattr(entity, "rotate"):
        rotated["entity_map"] = entity.rotate(derive_key(entity_root, "entity_tokens"))

    event_builder = system.get("event.builder")
    actor = getpass.getuser()
    ledger_hash = event_builder.ledger_entry(
        "security",
        inputs=list(old_ids.values()),
        outputs=list(new_ids.values()),
        payload={
            "event": "key_rotation",
            "actor": actor,
            "old_key_ids": old_ids,
            "new_key_ids": new_ids,
        },
    )

    return {
        "old_key_ids": old_ids,
        "new_key_ids": new_ids,
        "rotated": rotated,
        "ledger_hash": ledger_hash,
    }
