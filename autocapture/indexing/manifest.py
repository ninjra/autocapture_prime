"""Index manifest helpers for versioned retrieval."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IndexManifest:
    index_name: str
    version: int
    digest: str | None
    updated_at: str | None


def manifest_path(index_path: Path) -> Path:
    return index_path.with_suffix(index_path.suffix + ".manifest.json")


def load_manifest(index_path: Path, index_name: str) -> IndexManifest:
    path = manifest_path(index_path)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return IndexManifest(
                index_name=str(payload.get("index_name", index_name)),
                version=int(payload.get("version", 0)),
                digest=payload.get("digest"),
                updated_at=payload.get("updated_at"),
            )
        except Exception:
            pass
    return IndexManifest(index_name=index_name, version=0, digest=None, updated_at=None)


def bump_manifest(index_path: Path, index_name: str) -> IndexManifest:
    current = load_manifest(index_path, index_name)
    updated = IndexManifest(
        index_name=index_name,
        version=int(current.version) + 1,
        digest=current.digest,
        updated_at=_now_iso(),
    )
    _write_manifest(index_path, updated)
    return updated


def update_manifest_digest(index_path: Path, index_name: str, digest: str | None) -> IndexManifest:
    current = load_manifest(index_path, index_name)
    if current.digest == digest:
        return current
    updated = IndexManifest(
        index_name=index_name,
        version=int(current.version),
        digest=digest,
        updated_at=_now_iso(),
    )
    _write_manifest(index_path, updated)
    return updated


def _write_manifest(index_path: Path, manifest: IndexManifest) -> None:
    path = manifest_path(index_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "index_name": manifest.index_name,
        "version": int(manifest.version),
        "digest": manifest.digest,
        "updated_at": manifest.updated_at,
    }
    path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
