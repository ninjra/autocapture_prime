"""Hash helpers for contracts and plugins."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_directory(path: str | Path) -> str:
    """Hash a directory deterministically by path + contents."""
    root = Path(path)
    digest = hashlib.sha256()
    entries: list[tuple[str, Path]] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for dirname in list(dirs):
            dir_path = current_path / dirname
            if dir_path.is_symlink():
                raise ValueError(f"symlinks are not allowed in hashed directories: {dir_path}")
        for filename in files:
            file_path = current_path / filename
            if file_path.is_symlink():
                raise ValueError(f"symlinks are not allowed in hashed directories: {file_path}")
            if not file_path.is_file():
                continue
            if "__pycache__" in file_path.parts:
                continue
            if file_path.suffix == ".pyc":
                continue
            rel = file_path.relative_to(root).as_posix()
            entries.append((rel, file_path))

    def _sort_key(item: tuple[str, Path]) -> tuple[str, str]:
        rel = item[0]
        return (rel.casefold(), rel)

    for rel, file_path in sorted(entries, key=_sort_key):
        digest.update(rel.encode("utf-8"))
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_canonical(obj: Any) -> str:
    return sha256_text(dumps(obj))
