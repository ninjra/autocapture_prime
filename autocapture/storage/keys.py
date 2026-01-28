"""Key management utilities for MX storage."""

from __future__ import annotations

import json
from pathlib import Path

from autocapture_nx.kernel.keyring import KeyRing, KeyRecord


def load_keyring(config: dict) -> KeyRing:
    crypto = config.get("storage", {}).get("crypto", {})
    keyring_path = crypto.get("keyring_path", "data/vault/keyring.json")
    root_key_path = crypto.get("root_key_path", "data/vault/root.key")
    return KeyRing.load(keyring_path, legacy_root_path=root_key_path)


def export_keys(keyring: KeyRing, path: str | Path) -> None:
    purposes: dict[str, dict] = {}
    for purpose in keyring.purposes():
        purposes[purpose] = {
            "active_key_id": keyring.active_key_id_for(purpose),
            "keys": [
                {
                    "key_id": record.key_id,
                    "created_ts": record.created_ts,
                    "key_b64": record.key_b64,
                    "protected": record.protected,
                }
                for record in keyring.records_for(purpose)
            ],
        }
    payload = {"schema_version": 2, "purposes": purposes}
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def import_keys(keyring: KeyRing, path: str | Path) -> KeyRing:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    schema_version = int(payload.get("schema_version", 1) or 1)
    if schema_version == 1:
        purposes_payload = {purpose: payload for purpose in keyring.purposes()}
    else:
        purposes_payload = payload.get("purposes", {})
        if not isinstance(purposes_payload, dict):
            return keyring
    for purpose, data in purposes_payload.items():
        records = keyring.records_for(purpose)
        existing = {record.key_id for record in records}
        for item in data.get("keys", []):
            if item["key_id"] in existing:
                continue
            records.append(
                KeyRecord(
                    key_id=item["key_id"],
                    created_ts=item["created_ts"],
                    key_b64=item["key_b64"],
                    protected=bool(item.get("protected", False)),
                )
            )
    keyring.save()
    return keyring
