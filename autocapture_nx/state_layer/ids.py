"""Deterministic hashing and ID helpers for the state layer."""

from __future__ import annotations

import base64
import uuid
from typing import Any, Iterable

from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps
from autocapture_nx.kernel.hashing import sha256_bytes, sha256_text


def compute_config_hash(config: dict[str, Any]) -> str:
    """Stable hash for plugin configuration."""
    try:
        return sha256_text(canonical_dumps(config))
    except Exception:
        return sha256_text(str(sorted(config.items())))


def compute_cache_key(
    plugin_id: str,
    plugin_version: str,
    model_version: str,
    config_hash: str,
    input_artifact_ids: Iterable[str],
) -> str:
    payload = {
        "plugin_id": str(plugin_id),
        "plugin_version": str(plugin_version),
        "model_version": str(model_version),
        "config_hash": str(config_hash),
        "input_artifact_ids": list(input_artifact_ids),
    }
    return sha256_text(canonical_dumps(payload))


def compute_deterministic_id(preimage: bytes) -> str:
    digest = sha256_bytes(preimage)
    return str(uuid.UUID(hex=digest[:32]))


def deterministic_id_from_parts(parts: dict[str, Any]) -> str:
    payload = canonical_dumps(parts).encode("utf-8")
    return compute_deterministic_id(payload)


def compute_embedding_hash(blob: bytes) -> str:
    return sha256_bytes(blob)


def b64encode(blob: bytes) -> str:
    return base64.b64encode(blob).decode("ascii")


def b64decode(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))
