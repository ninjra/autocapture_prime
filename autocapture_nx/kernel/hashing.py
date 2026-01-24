"""Hash helpers for contracts and plugins."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


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
    def _iter_files():
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if "__pycache__" in file_path.parts:
                continue
            if file_path.suffix == ".pyc":
                continue
            yield file_path

    for file_path in sorted(_iter_files()):
        rel = file_path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
