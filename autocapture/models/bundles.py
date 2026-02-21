"""Deterministic bundle discovery and selection."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class BundleInfo:
    bundle_id: str
    version: str
    kind: str
    path: Path
    config: dict[str, Any]


def _parse_version(text: str) -> tuple[int, ...]:
    parts = []
    for token in str(text).split("."):
        try:
            parts.append(int(token))
        except Exception:
            parts.append(0)
    return tuple(parts)


def _bundle_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def discover_bundles(paths: Iterable[str | Path]) -> list[BundleInfo]:
    bundles: list[BundleInfo] = []
    for root in paths:
        base = Path(root)
        if not base.exists():
            continue
        for manifest_path in base.rglob("bundle.json"):
            payload = _bundle_manifest(manifest_path)
            if not isinstance(payload, dict):
                continue
            bundle_id = str(payload.get("bundle_id", "")).strip()
            version = str(payload.get("version", "")).strip()
            kind = str(payload.get("kind", "")).strip()
            if not bundle_id or not version or not kind:
                continue
            bundles.append(
                BundleInfo(
                    bundle_id=bundle_id,
                    version=version,
                    kind=kind,
                    path=manifest_path.parent,
                    config=payload,
                )
            )
    return bundles


def default_bundle_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.getenv("AUTOCAPTURE_BUNDLE_DIR", "").strip()
    if env:
        paths.append(Path(env))
    if os.name == "nt":
        paths.append(Path(r"D:\autocapture\bundles"))
    return paths


def select_bundle(kind: str, paths: Iterable[str | Path] | None = None) -> BundleInfo | None:
    search = list(paths) if paths is not None else default_bundle_paths()
    candidates = [b for b in discover_bundles(search) if b.kind == kind]
    if not candidates:
        return None
    candidates.sort(
        key=lambda b: (
            b.bundle_id,
            tuple(-v for v in _parse_version(b.version)),
        )
    )
    return candidates[0]
