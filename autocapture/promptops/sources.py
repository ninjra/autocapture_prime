"""Prompt source snapshot utilities."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from autocapture.core.hashing import hash_canonical


@dataclass(frozen=True)
class SourceSnapshot:
    source_id: str
    kind: str
    sha256: str
    size: int
    path: str | None = None


def _sha256_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def _normalize_sources(sources: Iterable[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for src in sources:
        if isinstance(src, str):
            normalized.append({"path": src})
        elif isinstance(src, dict):
            normalized.append(dict(src))
        else:
            normalized.append({"text": str(src)})
    return normalized


def snapshot_sources(sources: Iterable[Any], *, allow_web: bool = False) -> dict[str, Any]:
    items: list[SourceSnapshot] = []
    for entry in _normalize_sources(sources):
        if "url" in entry and not allow_web:
            continue
        if "bytes" in entry:
            data = entry["bytes"]
            if isinstance(data, bytearray):
                data = bytes(data)
            if isinstance(data, str):
                data = data.encode("utf-8")
            if not isinstance(data, (bytes, bytearray)):
                data = str(data).encode("utf-8")
            path = entry.get("path")
            items.append(
                SourceSnapshot(
                    source_id=str(entry.get("id") or entry.get("name") or (Path(path).name if path else "inline")),
                    kind="file",
                    sha256=_sha256_bytes(bytes(data)),
                    size=len(data),
                    path=str(path) if path else None,
                )
            )
            continue
        if "text" in entry:
            text = entry["text"]
            data = text.encode("utf-8")
            items.append(
                SourceSnapshot(
                    source_id=str(entry.get("id") or entry.get("name") or "inline"),
                    kind="text",
                    sha256=_sha256_bytes(data),
                    size=len(data),
                    path=str(entry.get("path")) if entry.get("path") else None,
                )
            )
        elif "path" in entry:
            path = Path(entry["path"])
            data = path.read_bytes() if path.exists() else b""
            items.append(
                SourceSnapshot(
                    source_id=str(entry.get("id") or path.name),
                    kind="file",
                    sha256=_sha256_bytes(data),
                    size=len(data),
                    path=str(path),
                )
            )
    payload = [item.__dict__ for item in items]
    return {
        "sources": payload,
        "combined_hash": hash_canonical(payload),
    }


class PromptBundle:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root) if root else None

    def snapshot(self, sources: Iterable[Any]) -> dict[str, Any]:
        resolved: list[Any] = []
        for src in sources:
            if isinstance(src, str) and self.root:
                resolved.append(str(self.root / src))
            else:
                resolved.append(src)
        return snapshot_sources(resolved)


def create_prompt_bundle(plugin_id: str) -> PromptBundle:
    return PromptBundle()
