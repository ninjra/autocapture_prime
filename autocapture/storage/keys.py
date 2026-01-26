"""Key management utilities for MX storage."""

from __future__ import annotations

import json
from pathlib import Path

from autocapture_nx.kernel.keyring import KeyRing


def load_keyring(config: dict) -> KeyRing:
    crypto = config.get("storage", {}).get("crypto", {})
    keyring_path = crypto.get("keyring_path", "data/vault/keyring.json")
    root_key_path = crypto.get("root_key_path", "data/vault/root.key")
    return KeyRing.load(keyring_path, legacy_root_path=root_key_path)


def export_keys(keyring: KeyRing, path: str | Path) -> None:
    payload = {
        "schema_version": 1,
        "active_key_id": keyring.active_key_id,
        "keys": [
            {
                "key_id": record.key_id,
                "created_ts": record.created_ts,
                "key_b64": record.key_b64,
                "protected": record.protected,
            }
            for record in keyring.records
        ],
    }
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def import_keys(keyring: KeyRing, path: str | Path) -> KeyRing:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    existing = {record.key_id for record in keyring.records}
    for item in payload.get("keys", []):
        if item["key_id"] in existing:
            continue
        keyring.records.append(
            type(keyring.records[0])(
                key_id=item["key_id"],
                created_ts=item["created_ts"],
                key_b64=item["key_b64"],
                protected=bool(item.get("protected", False)),
            )
        )
    keyring.save()
    return keyring
