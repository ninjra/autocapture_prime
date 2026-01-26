"""LoRA training pipeline (deterministic manifest)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture.core.hashing import hash_canonical
from autocapture.training.datasets import Dataset


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


@dataclass(frozen=True)
class TrainingArtifact:
    path: str
    sha256: str


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_lora(
    dataset: Dataset,
    *,
    params: dict[str, Any] | None = None,
    output_dir: str | Path = "artifacts/training",
    run_id: str | None = None,
    created_at: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    params = _normalize_value(params or {})
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    output_dir = Path(output_dir) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"dataset_hash": dataset.dataset_hash, "params": params, "method": "lora"}
    artifact_data = json.dumps(payload, sort_keys=True).encode("utf-8")
    artifact_path = output_dir / "lora_weights.bin"
    if not dry_run:
        artifact_path.write_bytes(artifact_data)
    artifact = TrainingArtifact(path=str(artifact_path), sha256=_sha256_bytes(artifact_data))
    manifest = {
        "manifest_version": 1,
        "run_id": run_id,
        "created_at": created_at,
        "method": "lora",
        "dataset": {"name": dataset.name, "hash": dataset.dataset_hash, "size": len(dataset.items)},
        "params": params,
        "artifacts": [artifact.__dict__],
        "local_only": True,
    }
    manifest_hash = hash_canonical(manifest)
    manifest["manifest_hash"] = manifest_hash
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest
