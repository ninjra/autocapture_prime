"""Hash helpers for contracts and plugins."""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps


_HASH_CACHE_ENABLED = os.getenv("AUTOCAPTURE_HASH_CACHE", "1").lower() not in {"0", "false", "no"}
_DIR_HASH_CACHE: dict[str, tuple[str, str]] = {}
_DIR_HASH_LOCK = threading.Lock()

_TEXT_LF_NORMALIZE_SUFFIXES = {
    ".py",
    ".pyi",
    ".json",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".ps1",
    ".sh",
    ".csv",
    ".tsv",
}


def _iter_bytes_for_hash(path: Path):
    """Yield bytes for hashing.

    For common text formats we normalize CRLF/CR to LF so plugin/contracts lock
    hashes remain stable across Windows/WSL even when git autocrlf is enabled.
    """

    suffix = path.suffix.lower()
    normalize_newlines = suffix in _TEXT_LF_NORMALIZE_SUFFIXES
    prev_cr = False
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            if not normalize_newlines:
                yield chunk
                continue
            if prev_cr:
                if chunk.startswith(b"\n"):
                    yield b"\n"
                    chunk = chunk[1:]
                else:
                    yield b"\n"
                prev_cr = False
            if chunk.endswith(b"\r"):
                prev_cr = True
                chunk = chunk[:-1]
            if chunk:
                # Replace CRLF -> LF within the chunk, then normalize any remaining CR.
                chunk = chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                if chunk:
                    yield chunk
        if prev_cr:
            yield b"\n"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    file_path = Path(path)
    for chunk in _iter_bytes_for_hash(file_path):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dir_fingerprint(entries: list[tuple[str, Path, os.stat_result]]) -> str:
    digest = hashlib.sha256()

    def _sort_key(item: tuple[str, Path, os.stat_result]) -> tuple[str, str]:
        rel = item[0]
        return (rel.casefold(), rel)

    for rel, _path, stat in sorted(entries, key=_sort_key):
        digest.update(rel.encode("utf-8"))
        digest.update(str(stat.st_size).encode("utf-8"))
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        ctime_ns = getattr(stat, "st_ctime_ns", None)
        if ctime_ns is not None:
            digest.update(str(ctime_ns).encode("utf-8"))
        inode = getattr(stat, "st_ino", None)
        if inode is not None:
            digest.update(str(inode).encode("utf-8"))
    return digest.hexdigest()


def sha256_directory(path: str | Path) -> str:
    """Hash a directory deterministically by path + contents."""
    root = Path(path)
    digest = hashlib.sha256()
    entries: list[tuple[str, Path, os.stat_result]] = []
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
            try:
                stat = file_path.stat()
            except FileNotFoundError:
                continue
            entries.append((rel, file_path, stat))

    fingerprint = _dir_fingerprint(entries)
    root_key = str(root.resolve())
    if _HASH_CACHE_ENABLED:
        with _DIR_HASH_LOCK:
            cached = _DIR_HASH_CACHE.get(root_key)
        if cached and cached[0] == fingerprint:
            return cached[1]

    def _sort_key(item: tuple[str, Path, os.stat_result]) -> tuple[str, str]:
        rel = item[0]
        return (rel.casefold(), rel)

    for rel, file_path, _stat in sorted(entries, key=_sort_key):
        digest.update(rel.encode("utf-8"))
        for chunk in _iter_bytes_for_hash(file_path):
            digest.update(chunk)
    result = digest.hexdigest()
    if _HASH_CACHE_ENABLED:
        with _DIR_HASH_LOCK:
            _DIR_HASH_CACHE[root_key] = (fingerprint, result)
    return result


def clear_directory_hash_cache() -> None:
    """Clear cached directory hashes to force recomputation."""
    if not _HASH_CACHE_ENABLED:
        return
    with _DIR_HASH_LOCK:
        _DIR_HASH_CACHE.clear()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_canonical(obj: Any) -> str:
    return sha256_text(dumps(obj))
