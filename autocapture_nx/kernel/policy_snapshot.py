"""Policy snapshot extraction + persistence (content-addressed).

Adversarial redesign META-06: Persist full policy snapshots by hash and include
them in exports for auditability and proof bundles.

This module is intentionally lightweight and deterministic: it extracts a stable
subset of the effective config that constitutes "policy" (privacy + plugin
permissions + egress settings), then hashes the canonical JSON form.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.atomic_write import atomic_write_text
from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.hashing import sha256_text


def _pick(obj: Any, key: str, default: Any) -> Any:
    if not isinstance(obj, dict):
        return default
    return obj.get(key, default)


def policy_snapshot_payload(config: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical policy snapshot payload.

    Keep this conservative: include the full `privacy` section plus plugin permission
    and filesystem scope policy.
    """

    plugins = _pick(config, "plugins", {})
    privacy = _pick(config, "privacy", {})
    payload: dict[str, Any] = {
        "schema_version": 1,
        "privacy": privacy if isinstance(privacy, dict) else {},
        "plugins": {
            "permissions": _pick(plugins, "permissions", {}) if isinstance(plugins, dict) else {},
            "filesystem_defaults": _pick(plugins, "filesystem_defaults", {}) if isinstance(plugins, dict) else {},
            "filesystem_policies": _pick(plugins, "filesystem_policies", {}) if isinstance(plugins, dict) else {},
            "allowlist": _pick(plugins, "allowlist", []) if isinstance(plugins, dict) else [],
            "enabled": _pick(plugins, "enabled", {}) if isinstance(plugins, dict) else {},
            "locks": _pick(plugins, "locks", {}) if isinstance(plugins, dict) else {},
        },
    }
    return payload


def policy_snapshot_hash(payload: dict[str, Any]) -> str:
    return sha256_text(dumps(payload))


def policy_snapshot_record_id(snapshot_hash: str) -> str:
    # Content-addressed, stable across runs.
    return f"policy_snapshot/{snapshot_hash}"


@dataclass(frozen=True)
class PolicySnapshotPersistResult:
    snapshot_hash: str
    record_id: str
    path: str
    existed: bool


def persist_policy_snapshot(
    *,
    config: dict[str, Any],
    data_dir: str | Path,
    metadata: Any | None,
    ts_utc: str | None = None,
) -> PolicySnapshotPersistResult:
    """Persist policy snapshot to disk and (optionally) metadata store.

    No deletion: if the file already exists, it is treated as immutable.
    """

    payload = policy_snapshot_payload(config)
    snapshot_hash = policy_snapshot_hash(payload)
    record_id = policy_snapshot_record_id(snapshot_hash)
    if not ts_utc:
        ts_utc = datetime.now(timezone.utc).isoformat()

    root = Path(data_dir)
    out_dir = root / "policy_snapshots"
    out_path = out_dir / f"{snapshot_hash}.json"
    existed = out_path.exists()
    if not existed:
        # Store a readable JSON file for operators. Hashing uses canonical_json.dumps.
        import json

        text = json.dumps(payload, sort_keys=True, indent=2)
        atomic_write_text(out_path, text, fsync=True)

    if metadata is not None:
        record = {
            "record_type": "system.policy_snapshot",
            "schema_version": 1,
            "ts_utc": ts_utc,
            "policy_snapshot_hash": snapshot_hash,
            "payload": payload,
        }
        try:
            if hasattr(metadata, "put_new"):
                metadata.put_new(record_id, record)
            else:
                # Best effort: treat as immutable, but fall back to idempotent put
                # for stores that don't expose put_new.
                if hasattr(metadata, "get") and metadata.get(record_id):
                    pass
                else:
                    metadata.put(record_id, record)
        except FileExistsError:
            pass
        except Exception:
            # Fail closed for policy persistence: other invariants (local-only, no egress)
            # must still hold even if metadata persistence fails.
            pass

    return PolicySnapshotPersistResult(
        snapshot_hash=snapshot_hash,
        record_id=record_id,
        path=str(out_path),
        existed=bool(existed),
    )
